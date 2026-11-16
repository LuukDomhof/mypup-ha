"""The MyPup integration."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MyPupApiClient, MyPupApiError, MyPupSessionData
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_COOKIES,
    CONF_EXPIRES_AT,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .coordinator import MyPupDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]
SERVICE_UNLOCK_LOCKER = "unlock_locker"
SERVICE_UNLOCK_SCHEMA = vol.Schema(
    {
        vol.Optional("shipment_uid"): str,
        vol.Optional("locker"): str,
    }
)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update coordinator polling interval and refresh when options change."""
    coordinator: MyPupDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    scan_minutes = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES))
    coordinator.update_interval = timedelta(minutes=scan_minutes)
    await coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MyPup from a config entry."""
    session = async_get_clientsession(hass)
    session_data = MyPupSessionData(
        access_token=entry.data.get(CONF_ACCESS_TOKEN, ""),
        expires_at=entry.data.get(CONF_EXPIRES_AT, 0.0),
        auth_cookies=dict(entry.data.get(CONF_AUTH_COOKIES, {})),
    )
    client = MyPupApiClient(session, session_data=session_data)
    coordinator = MyPupDataUpdateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if not hass.services.has_service(DOMAIN, SERVICE_UNLOCK_LOCKER):

        async def _handle_unlock_locker(call: ServiceCall) -> None:
            shipment_uid = (call.data.get("shipment_uid") or "").strip()
            locker = (call.data.get("locker") or "").strip()
            coordinators: list[MyPupDataUpdateCoordinator] = list(
                hass.data.get(DOMAIN, {}).values()
            )
            if not coordinators:
                raise HomeAssistantError("No MyPup integration entries are loaded.")

            target_coord = coordinators[0]
            if not shipment_uid:
                ready = target_coord.data.get("ready_shipments", [])
                if locker:
                    match = next(
                        (
                            item
                            for item in ready
                            if str(item.get("transferDetails") or "").strip() == locker
                        ),
                        None,
                    )
                    if not match:
                        raise HomeAssistantError(
                            f"No ReadyForPickup parcel found in locker {locker}."
                        )
                    shipment_uid = match.get("shipmentUid") or ""
                else:
                    if not ready:
                        raise HomeAssistantError("No parcels ready for pickup to unlock.")
                    shipment_uid = ready[0].get("shipmentUid") or ""

            if not shipment_uid:
                raise HomeAssistantError("Missing shipmentUid to unlock.")

            _LOGGER.info(
                "Service mypup.unlock_locker called for shipmentUid=%s (locker=%s)",
                shipment_uid,
                locker or "auto",
            )
            try:
                await target_coord.client.unlock_shipment_locker(shipment_uid)
            except MyPupApiError as err:
                _LOGGER.error("Service mypup.unlock_locker failed for %s: %s", shipment_uid, err)
                raise HomeAssistantError(f"Failed to unlock MyPup locker: {err}") from err

            await target_coord.async_request_refresh()

        hass.services.async_register(
            DOMAIN,
            SERVICE_UNLOCK_LOCKER,
            _handle_unlock_locker,
            schema=SERVICE_UNLOCK_SCHEMA,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_UNLOCK_LOCKER)
    return unload_ok
