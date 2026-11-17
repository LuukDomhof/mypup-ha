"""The MyPup integration."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
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
from .coordinator import MyPupConfigEntry, MyPupDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]
SERVICE_UNLOCK_LOCKER = "unlock_locker"
SERVICE_UNLOCK_SCHEMA = vol.Schema(
    {
        vol.Optional("shipment_uid"): str,
        vol.Optional("locker"): str,
        vol.Optional("config_entry_id"): str,
    }
)


async def _async_options_updated(hass: HomeAssistant, entry: MyPupConfigEntry) -> None:
    """Update coordinator polling interval and refresh when options change."""
    coordinator = entry.runtime_data
    scan_minutes = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES))
    coordinator.update_interval = timedelta(minutes=scan_minutes)
    await coordinator.async_request_refresh()


def _resolve_target_shipment(
    entries: list[MyPupConfigEntry],
    shipment_uid: str,
    locker: str,
) -> tuple[MyPupDataUpdateCoordinator, str]:
    """Find the coordinator and shipmentUid matching the requested UID or locker."""
    for entry in entries:
        coord = entry.runtime_data
        data = coord.data or {}
        ready = data.get("ready_shipments", [])
        all_shipments = data.get("shipments", [])

        if shipment_uid:
            if any(item.get("shipmentUid") == shipment_uid for item in all_shipments):
                return coord, shipment_uid
        elif locker:
            match = next(
                (
                    item
                    for item in ready
                    if str(item.get("transferDetails") or "").strip() == locker
                ),
                None,
            )
            if match and match.get("shipmentUid"):
                return coord, match["shipmentUid"]
        elif ready and ready[0].get("shipmentUid"):
            return coord, ready[0]["shipmentUid"]

    if shipment_uid:
        # Fallback to first entry if shipment_uid wasn't in the cached page
        return entries[0].runtime_data, shipment_uid
    if locker:
        raise HomeAssistantError(f"No ReadyForPickup parcel found in locker {locker}.")
    raise HomeAssistantError("No parcels ready for pickup to unlock.")


async def async_setup_entry(hass: HomeAssistant, entry: MyPupConfigEntry) -> bool:
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

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if not hass.services.has_service(DOMAIN, SERVICE_UNLOCK_LOCKER):

        async def _handle_unlock_locker(call: ServiceCall) -> ServiceResponse:
            shipment_uid = (call.data.get("shipment_uid") or "").strip()
            locker = (call.data.get("locker") or "").strip()
            config_entry_id = (call.data.get("config_entry_id") or "").strip()

            loaded_entries: list[MyPupConfigEntry] = hass.config_entries.async_loaded_entries(
                DOMAIN
            )
            if config_entry_id:
                loaded_entries = [
                    e for e in loaded_entries if e.entry_id == config_entry_id
                ]
            if not loaded_entries:
                raise HomeAssistantError("No matching MyPup integration entries are loaded.")

            target_coord, resolved_uid = _resolve_target_shipment(
                loaded_entries, shipment_uid, locker
            )

            _LOGGER.info(
                "Service mypup.unlock_locker called for shipmentUid=%s (locker=%s)",
                resolved_uid,
                locker or "auto",
            )
            try:
                resp = await target_coord.client.unlock_shipment_locker(resolved_uid)
            except MyPupApiError as err:
                _LOGGER.error("Service mypup.unlock_locker failed for %s: %s", resolved_uid, err)
                raise HomeAssistantError(f"Failed to unlock MyPup locker: {err}") from err

            await target_coord.async_request_refresh()
            if call.return_response:
                return {
                    "shipment_uid": resolved_uid,
                    "is_success": bool(resp.get("isSuccess", True)),
                    "result_code": resp.get("resultCode"),
                }
            return None

        hass.services.async_register(
            DOMAIN,
            SERVICE_UNLOCK_LOCKER,
            _handle_unlock_locker,
            schema=SERVICE_UNLOCK_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MyPupConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        remaining = [
            e
            for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining:
            hass.services.async_remove(DOMAIN, SERVICE_UNLOCK_LOCKER)
    return unload_ok
