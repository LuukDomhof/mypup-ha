"""DataUpdateCoordinator for MyPup."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MyPupApiClient, MyPupApiError, MyPupAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_COOKIES,
    CONF_EXPIRES_AT,
    CONF_FETCH_ACCESS_CODES,
    CONF_SCAN_INTERVAL,
    CONF_SHIPMENTS_LIMIT,
    DEFAULT_FETCH_ACCESS_CODES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_SHIPMENTS_LIMIT,
    DOMAIN,
    STATE_READY_FOR_PICKUP,
)

_LOGGER = logging.getLogger(__name__)


class MyPupDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls MyPup shipments and pickup point info."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MyPupApiClient,
        entry: ConfigEntry,
    ) -> None:
        scan_minutes = int(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_minutes),
        )
        self.client = client
        self.entry = entry

    async def _async_fetch_access_codes(self, shipment_uid: str) -> dict[str, str | None]:
        """Fetch PIN and QR code for a ReadyForPickup shipment, returning empty on error."""
        pin: str | None = None
        qr_code: str | None = None
        try:
            resp = await self.client.query_shipment_access_config(shipment_uid)
            codes = (resp.get("accessConfig") or {}).get("codes") or []
            for code in codes:
                code_type = (code.get("type") or "").lower()
                if code_type == "pin" and not pin:
                    pin = code.get("code")
                elif code_type == "qr" and not qr_code:
                    qr_code = code.get("code")
        except MyPupApiError as err:
            _LOGGER.debug(
                "Could not fetch access config for shipment %s: %s", shipment_uid, err
            )
        return {"pin": pin, "qr_code": qr_code}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            previous_token = self.entry.data.get(CONF_ACCESS_TOKEN)
            previous_cookies = self.entry.data.get(CONF_AUTH_COOKIES)

            limit = int(
                self.entry.options.get(CONF_SHIPMENTS_LIMIT, DEFAULT_SHIPMENTS_LIMIT)
            )
            fetch_codes = bool(
                self.entry.options.get(CONF_FETCH_ACCESS_CODES, DEFAULT_FETCH_ACCESS_CODES)
            )

            shipments_resp = await self.client.query_shipments(page_no=1, page_size=limit)
            pup_resp = await self.client.query_main_pickup_point()

            sd = self.client.session_data
            if sd.access_token != previous_token or sd.auth_cookies != previous_cookies:
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={
                        **self.entry.data,
                        CONF_ACCESS_TOKEN: sd.access_token,
                        CONF_EXPIRES_AT: sd.expires_at,
                        CONF_AUTH_COOKIES: sd.auth_cookies,
                    },
                )

            items = shipments_resp.get("items", [])
            ready: list[dict[str, Any]] = []
            access_codes: dict[str, dict[str, str | None]] = {}

            for item in items:
                if item.get("stateCode") == STATE_READY_FOR_PICKUP:
                    ready.append(item)
                    uid = item.get("shipmentUid")
                    if fetch_codes and uid:
                        access_codes[uid] = await self._async_fetch_access_codes(uid)

            return {
                "shipments": items,
                "ready_shipments": ready,
                "access_codes": access_codes,
                "pickup_point": pup_resp,
            }
        except MyPupAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MyPupApiError as err:
            raise UpdateFailed(str(err)) from err
