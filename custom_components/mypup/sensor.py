"""Sensor platform for MyPup."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import STATE_READY_FOR_PICKUP
from .coordinator import (
    MyPupConfigEntry,
    MyPupDataUpdateCoordinator,
    _format_parcel,
    build_mypup_device_info,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyPupConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MyPup sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MyPupIncomingParcelsSensor(coordinator, entry),
            MyPupReadyParcelsSensor(coordinator, entry),
            MyPupPreviousParcelsSensor(coordinator, entry),
            MyPupTotalParcelsSensor(coordinator, entry),
            MyPupMainPickupPointSensor(coordinator, entry),
        ]
    )


class MyPupBaseSensor(CoordinatorEntity[MyPupDataUpdateCoordinator], SensorEntity):
    """Base class for MyPup sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = build_mypup_device_info(coordinator, entry)


class MyPupIncomingParcelsSensor(MyPupBaseSensor):
    """Number of incoming (pre-locker) parcels."""

    _attr_translation_key = "incoming_parcels"
    _attr_icon = "mdi:truck-delivery"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_incoming_parcels"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("incoming_shipments", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "parcels": [
                _format_parcel(item)
                for item in self.coordinator.data.get("incoming_shipments", [])
            ]
        }


class MyPupReadyParcelsSensor(MyPupBaseSensor):
    """Number of parcels ready for pickup."""

    _attr_translation_key = "ready_parcels"
    _attr_icon = "mdi:package-variant-closed-check"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_ready_parcels"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("ready_shipments", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        access_codes = self.coordinator.data.get("access_codes", {})
        return {
            "parcels": [
                _format_parcel(item, access_codes.get(item.get("shipmentUid"), {}))
                for item in self.coordinator.data.get("ready_shipments", [])
            ]
        }


class MyPupPreviousParcelsSensor(MyPupBaseSensor):
    """Number of previous/completed parcels."""

    _attr_translation_key = "previous_parcels"
    _attr_icon = "mdi:package-check"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_previous_parcels"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("previous_shipments", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "parcels": [
                _format_parcel(item)
                for item in self.coordinator.data.get("previous_shipments", [])
            ]
        }


class MyPupTotalParcelsSensor(MyPupBaseSensor):
    """Total number of tracked parcels."""

    _attr_translation_key = "total_parcels"
    _attr_icon = "mdi:package-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_parcels"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("shipments", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        access_codes = self.coordinator.data.get("access_codes", {})
        return {
            "parcels": [
                _format_parcel(
                    item,
                    access_codes.get(item.get("shipmentUid"), {})
                    if item.get("stateCode") == STATE_READY_FOR_PICKUP
                    else None,
                )
                for item in self.coordinator.data.get("shipments", [])
            ]
        }


class MyPupMainPickupPointSensor(MyPupBaseSensor):
    """Primary MyPup Pick Up Point."""

    _attr_translation_key = "main_pickup_point"
    _attr_icon = "mdi:locker-multiple"

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_main_pup"

    @property
    def native_value(self) -> str | None:
        pup = self.coordinator.data.get("pickup_point", {}).get("pickUpPoint", {})
        return pup.get("name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get("pickup_point", {})
        pup = data.get("pickUpPoint", {})
        return {
            "mail_code": data.get("mailCode"),
            "pup_uid": pup.get("pupUid"),
            "delivery_address_lines": data.get("deliveryAddressLines"),
        }
