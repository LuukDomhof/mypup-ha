"""Diagnostics support for MyPup."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import MyPupConfigEntry

TO_REDACT = {
    "access_token",
    "auth_cookies",
    "pin",
    "qr_code",
    "mailCode",
    "userUid",
    "emailAddress",
    "phoneNumber",
    "fullName",
    "firstName",
    "lastName",
    "toUser",
    "fromUser",
    "deliveryAddressLines",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MyPupConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a MyPup config entry with sensitive fields redacted."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "options": dict(entry.options),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "data": async_redact_data(coordinator.data or {}, TO_REDACT),
    }
