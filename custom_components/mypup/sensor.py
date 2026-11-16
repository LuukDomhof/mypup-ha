"""Sensor platform for MyPup."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MyPupDataUpdateCoordinator, build_mypup_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MyPup sensors."""
    coordinator: MyPupDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            MyPupReadyParcelsSensor(coordinator, entry),
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


class MyPupReadyParcelsSensor(MyPupBaseSensor):
    """Number of parcels ready for pickup."""

    _attr_name = "Parcels ready for pickup"
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
        parcels = []
        for item in self.coordinator.data.get("ready_shipments", []):
            uid = item.get("shipmentUid")
            codes = access_codes.get(uid, {})
            parcels.append(
                {
                    "shipment_uid": uid,
                    "reference_no": item.get("referenceNo"),
                    "description": item.get("description"),
                    "pickup_point": item.get("bookedPupName"),
                    "locker": item.get("transferDetails"),
                    "state_start": item.get("stateStart"),
                    "pin": codes.get("pin"),
                    "qr_code": codes.get("qr_code"),
                }
            )
        return {"parcels": parcels}


class MyPupTotalParcelsSensor(MyPupBaseSensor):
    """Total number of tracked parcels."""

    _attr_name = "Total parcels"
    _attr_icon = "mdi:package-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MyPupDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_parcels"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("shipments", []))


class MyPupMainPickupPointSensor(MyPupBaseSensor):
    """Primary MyPup Pick Up Point."""

    _attr_name = "Main pickup point"
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
