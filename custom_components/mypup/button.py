"""Button platform for MyPup."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MyPupApiError
from .coordinator import (
    MyPupConfigEntry,
    MyPupDataUpdateCoordinator,
    build_mypup_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyPupConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MyPup button entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MyPupUnlockNextLockerButton(coordinator, entry),
            MyPupRefreshButton(coordinator, entry),
        ]
    )


class MyPupUnlockNextLockerButton(CoordinatorEntity[MyPupDataUpdateCoordinator], ButtonEntity):
    """Button to unlock the locker for the next parcel ready for pickup."""

    _attr_has_entity_name = True
    _attr_translation_key = "unlock_ready_locker"
    _attr_icon = "mdi:locker"

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_unlock_ready_locker"
        self._attr_device_info = build_mypup_device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        return super().available and len(self.coordinator.data.get("ready_shipments", [])) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ready = self.coordinator.data.get("ready_shipments", [])
        if not ready:
            return {}
        target = ready[0]
        return {
            "next_shipment_uid": target.get("shipmentUid"),
            "next_reference_no": target.get("referenceNo"),
            "next_description": target.get("description"),
            "next_pickup_point": target.get("bookedPupName"),
            "next_locker": target.get("transferDetails"),
        }

    async def async_press(self) -> None:
        """Unlock the locker for the first ReadyForPickup shipment."""
        ready = self.coordinator.data.get("ready_shipments", [])
        if not ready:
            _LOGGER.warning("Unlock ready locker pressed, but no ReadyForPickup shipments exist")
            raise HomeAssistantError("No parcels ready for pickup to unlock.")

        target = ready[0]
        shipment_uid = target.get("shipmentUid")
        if not shipment_uid:
            raise HomeAssistantError("Ready parcel is missing shipmentUid.")

        _LOGGER.info(
            "Unlocking MyPup locker %s at %s for shipment %s (%s)",
            target.get("transferDetails"),
            target.get("bookedPupName"),
            target.get("referenceNo"),
            shipment_uid,
        )
        try:
            await self.coordinator.client.unlock_shipment_locker(shipment_uid)
        except MyPupApiError as err:
            _LOGGER.error("Failed to unlock MyPup locker for %s: %s", shipment_uid, err)
            raise HomeAssistantError(f"Failed to unlock MyPup locker: {err}") from err

        await self.coordinator.async_request_refresh()


class MyPupRefreshButton(CoordinatorEntity[MyPupDataUpdateCoordinator], ButtonEntity):
    """Button to manually refresh MyPup shipments."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_parcels"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = build_mypup_device_info(coordinator, entry)

    async def async_press(self) -> None:
        """Trigger an immediate coordinator refresh."""
        await self.coordinator.async_request_refresh()
