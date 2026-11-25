"""Unit tests for the MyPup integration."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def _install_ha_stubs() -> None:
    """Install lightweight stubs when homeassistant/aiohttp are not installed."""
    if "aiohttp" not in sys.modules:
        aiohttp_mod = types.ModuleType("aiohttp")

        class ClientError(Exception):
            pass

        class ClientSession:
            pass

        aiohttp_mod.ClientError = ClientError
        aiohttp_mod.ClientSession = ClientSession
        sys.modules["aiohttp"] = aiohttp_mod

    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        ha_ce = types.ModuleType("homeassistant.config_entries")
        ha_core = types.ModuleType("homeassistant.core")
        ha_exc = types.ModuleType("homeassistant.exceptions")
        ha_helpers = types.ModuleType("homeassistant.helpers")
        ha_dr = types.ModuleType("homeassistant.helpers.device_registry")
        ha_uc = types.ModuleType("homeassistant.helpers.update_coordinator")

        class _Subscriptable:
            def __class_getitem__(cls, item):
                return cls

        class ConfigEntry(_Subscriptable):
            pass

        class HomeAssistant:
            pass

        class ConfigEntryAuthFailed(Exception):
            pass

        class DeviceEntryType:
            SERVICE = "service"

        class DeviceInfo(dict):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

        class DataUpdateCoordinator(_Subscriptable):
            def __init__(self, hass, logger, *, name, update_interval):
                self.hass = hass
                self.logger = logger
                self.name = name
                self.update_interval = update_interval
                self.data = {}

        class UpdateFailed(Exception):
            pass

        ha_ce.ConfigEntry = ConfigEntry
        ha_core.HomeAssistant = HomeAssistant
        ha_exc.ConfigEntryAuthFailed = ConfigEntryAuthFailed
        ha_dr.DeviceEntryType = DeviceEntryType
        ha_dr.DeviceInfo = DeviceInfo
        ha_uc.DataUpdateCoordinator = DataUpdateCoordinator
        ha_uc.UpdateFailed = UpdateFailed

        sys.modules["homeassistant"] = ha
        sys.modules["homeassistant.config_entries"] = ha_ce
        sys.modules["homeassistant.core"] = ha_core
        sys.modules["homeassistant.exceptions"] = ha_exc
        sys.modules["homeassistant.helpers"] = ha_helpers
        sys.modules["homeassistant.helpers.device_registry"] = ha_dr
        sys.modules["homeassistant.helpers.update_coordinator"] = ha_uc


def _load_mypup_module(name: str):
    pkg_dir = Path(__file__).resolve().parents[1] / "custom_components" / "mypup"
    if "mypup_pkg" not in sys.modules:
        pkg = types.ModuleType("mypup_pkg")
        pkg.__path__ = [str(pkg_dir)]
        sys.modules["mypup_pkg"] = pkg
    full_name = f"mypup_pkg.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, pkg_dir / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_install_ha_stubs()
const_mod = _load_mypup_module("const")
api_mod = _load_mypup_module("api")
coord_mod = _load_mypup_module("coordinator")


def _make_jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


class TestMyPupApiHelpers(unittest.TestCase):
    """Test pure helper functions in api.py."""

    def test_parse_cookie_input_strips_prefix_and_newlines(self) -> None:
        raw = "Cookie: idsrv=abc;\nXSRF-TOKEN=xyz\r\n"
        parsed = api_mod.parse_cookie_input(raw)
        self.assertEqual(parsed, {"idsrv": "abc", "XSRF-TOKEN": "xyz"})

    def test_parse_cookie_input_json(self) -> None:
        parsed = api_mod.parse_cookie_input('{"idsrv": "abc"}')
        self.assertEqual(parsed, {"idsrv": "abc"})

    def test_extract_access_token_from_fragment_url(self) -> None:
        url = "https://mypup.app/Login/callback#id_token=id1&access_token=tok123&expires_in=3600"
        self.assertEqual(api_mod.extract_access_token_from_input(url), "tok123")

    def test_decode_jwt_claims(self) -> None:
        jwt = _make_jwt({"sub": "user-123", "exp": 9999999999})
        claims = api_mod.decode_jwt_claims(jwt)
        self.assertEqual(claims["sub"], "user-123")
        self.assertEqual(claims["exp"], 9999999999)


class TestMyPupCoordinator(unittest.TestCase):
    """Test coordinator shipment bucketing, concurrent code fetch, and events."""

    def _make_coordinator(self, items_sequence: list[list[dict]]):
        hass = MagicMock()
        hass.bus = MagicMock()
        hass.config_entries = MagicMock()

        entry = MagicMock()
        entry.entry_id = "entry-1"
        entry.title = "MyPup"
        entry.data = {
            const_mod.CONF_ACCESS_TOKEN: _make_jwt({"sub": "u1", "exp": 9999999999}),
            const_mod.CONF_EXPIRES_AT: 9999999999.0,
            const_mod.CONF_AUTH_COOKIES: {"idsrv": "cookie"},
        }
        entry.options = {
            const_mod.CONF_SCAN_INTERVAL: 5,
            const_mod.CONF_SHIPMENTS_LIMIT: 25,
            const_mod.CONF_FETCH_ACCESS_CODES: True,
        }

        client = MagicMock()
        client.session_data = api_mod.MyPupSessionData(
            access_token=entry.data[const_mod.CONF_ACCESS_TOKEN],
            expires_at=entry.data[const_mod.CONF_EXPIRES_AT],
            auth_cookies=dict(entry.data[const_mod.CONF_AUTH_COOKIES]),
        )
        side_effects = [{"items": items} for items in items_sequence]
        client.query_shipments = AsyncMock(side_effect=side_effects)
        client.query_main_pickup_point = AsyncMock(
            return_value={"pickUpPoint": {"name": "My Pick Up Point"}}
        )
        client.query_shipment_access_config = AsyncMock(
            return_value={
                "accessConfig": {
                    "codes": [
                        {"type": "Pin", "code": "1234"},
                        {"type": "Qr", "code": "QRDATA"},
                    ]
                }
            }
        )

        coord = coord_mod.MyPupDataUpdateCoordinator(hass, client, entry)
        return coord, hass, client

    def test_splits_incoming_ready_previous_and_fires_events_after_startup(self) -> None:
        poll1 = [
            {"shipmentUid": "s1", "stateCode": "Arrived", "referenceNo": "R1"},
            {"shipmentUid": "s4", "stateCode": "ReadyForDropoff", "referenceNo": "R4"},
            {"shipmentUid": "s2", "stateCode": "Received", "referenceNo": "R2"},
        ]
        poll2 = [
            {"shipmentUid": "s1", "stateCode": "ReadyForPickup", "referenceNo": "R1", "transferDetails": "15"},
            {"shipmentUid": "s3", "stateCode": "Registered", "referenceNo": "R3"},
            {"shipmentUid": "s4", "stateCode": "ReadyForDropoff", "referenceNo": "R4"},
            {"shipmentUid": "s2", "stateCode": "Received", "referenceNo": "R2"},
        ]
        coord, hass, client = self._make_coordinator([poll1, poll2])

        data1 = asyncio.run(coord._async_update_data())
        self.assertEqual(len(data1["incoming_shipments"]), 2)
        self.assertEqual(len(data1["ready_shipments"]), 0)
        self.assertEqual(len(data1["previous_shipments"]), 1)
        # Startup poll must not fire events
        hass.bus.async_fire.assert_not_called()

        data2 = asyncio.run(coord._async_update_data())
        self.assertEqual(len(data2["incoming_shipments"]), 2)
        self.assertEqual(len(data2["ready_shipments"]), 1)
        self.assertEqual(len(data2["previous_shipments"]), 1)
        self.assertEqual(data2["access_codes"]["s1"], {"pin": "1234", "qr_code": "QRDATA"})
        client.query_shipment_access_config.assert_awaited_once_with("s1")

        fired_events = [call.args[0] for call in hass.bus.async_fire.call_args_list]
        self.assertIn(const_mod.EVENT_PARCEL_READY, fired_events)
        self.assertIn(const_mod.EVENT_PARCEL_INCOMING, fired_events)


if __name__ == "__main__":
    unittest.main()
