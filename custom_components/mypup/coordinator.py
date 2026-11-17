"""DataUpdateCoordinator for MyPup."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
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
    EVENT_PARCEL_INCOMING,
    EVENT_PARCEL_READY,
    INCOMING_STATES,
    STATE_READY_FOR_PICKUP,
)

_LOGGER = logging.getLogger(__name__)

MyPupConfigEntry: TypeAlias = ConfigEntry["MyPupDataUpdateCoordinator"]


def build_mypup_device_info(
    coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry
) -> DeviceInfo:
    """Build a single logical Service DeviceInfo for the MyPup account/pickup point."""
    pup_name = (
        coordinator.data.get("pickup_point", {}).get("pickUpPoint", {}).get("name")
        if coordinator.data
        else None
    )
    name = f"MyPup ({pup_name})" if pup_name else entry.title or "MyPup"
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, entry.entry_id)},
        name=name,
        manufacturer="MyPup",
        model="Pick Up Point",
        configuration_url="https://mypup.app",
    )


def _format_parcel(
    item: dict[str, Any], codes: dict[str, str | None] | None = None
) -> dict[str, Any]:
    """Build a normalized parcel dictionary for attributes and events."""
    parcel: dict[str, Any] = {
        "shipment_uid": item.get("shipmentUid"),
        "reference_no": item.get("referenceNo"),
        "description": item.get("description"),
        "state_code": item.get("stateCode"),
        "pickup_point": item.get("bookedPupName"),
        "locker": item.get("transferDetails"),
        "state_start": item.get("stateStart"),
        "date_created": item.get("dateCreated"),
    }
    if codes is not None:
        parcel["pin"] = codes.get("pin")
        parcel["qr_code"] = codes.get("qr_code")
    return parcel


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
        self._known_states: dict[str, str] | None = None

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

    def _fire_transition_events(
        self,
        items: list[dict[str, Any]],
        access_codes: dict[str, dict[str, str | None]],
    ) -> None:
        """Fire HA events when shipments transition into incoming or ready states."""
        current_states = {
            item["shipmentUid"]: item.get("stateCode", "")
            for item in items
            if item.get("shipmentUid")
        }

        if self._known_states is None:
            # Skip firing events on initial startup poll
            self._known_states = current_states
            return

        for item in items:
            uid = item.get("shipmentUid")
            if not uid:
                continue
            new_state = item.get("stateCode", "")
            old_state = self._known_states.get(uid)
            if new_state == old_state:
                continue

            if new_state == STATE_READY_FOR_PICKUP:
                payload = _format_parcel(item, access_codes.get(uid, {}))
                self.hass.bus.async_fire(EVENT_PARCEL_READY, payload)
            elif new_state in INCOMING_STATES and old_state not in INCOMING_STATES:
                payload = _format_parcel(item)
                self.hass.bus.async_fire(EVENT_PARCEL_INCOMING, payload)

        self._known_states = current_states

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
            incoming: list[dict[str, Any]] = []
            ready: list[dict[str, Any]] = []
            previous: list[dict[str, Any]] = []
            ready_uids: list[str] = []

            for item in items:
                state = item.get("stateCode")
                uid = item.get("shipmentUid")
                if state == STATE_READY_FOR_PICKUP:
                    ready.append(item)
                    if fetch_codes and uid:
                        ready_uids.append(uid)
                elif state in INCOMING_STATES:
                    incoming.append(item)
                else:
                    previous.append(item)

            access_codes: dict[str, dict[str, str | None]] = {}
            if ready_uids:
                results = await asyncio.gather(
                    *(self._async_fetch_access_codes(uid) for uid in ready_uids)
                )
                access_codes = dict(zip(ready_uids, results, strict=True))

            self._fire_transition_events(items, access_codes)

            return {
                "shipments": items,
                "incoming_shipments": incoming,
                "ready_shipments": ready,
                "previous_shipments": previous,
                "access_codes": access_codes,
                "pickup_point": pup_resp,
            }
        except MyPupAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MyPupApiError as err:
            raise UpdateFailed(str(err)) from err
