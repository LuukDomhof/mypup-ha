"""Async API client for MyPup."""

from __future__ import annotations

import base64
import json
import logging
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    CLIENT_ID,
    OIDC_AUTHORIZE_URL,
    REDIRECT_URI,
    SCOPES,
)

_LOGGER = logging.getLogger(__name__)


class MyPupApiError(Exception):
    """Base exception for MyPup API errors."""


class MyPupAuthError(MyPupApiError):
    """Raised when authentication or silent token renewal fails."""


@dataclass
class MyPupSessionData:
    """OAuth access token and login.mypup.app session cookies for silent renewal."""

    access_token: str = ""
    expires_at: float = 0.0
    auth_cookies: dict[str, str] = field(default_factory=dict)


def parse_cookie_input(raw: str) -> dict[str, str]:
    """Parse a raw Cookie header string or JSON object into a {name: value} dict."""
    text = raw.strip().replace("\r", "").replace("\n", "")
    if text.lower().startswith("cookie:"):
        text = text[len("cookie:") :].strip()
    if not text:
        return {}
    if text.startswith("{"):
        data = json.loads(text)
        return {str(k): str(v) for k, v in data.items()}
    cookies: dict[str, str] = {}
    for part in text.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def extract_access_token_from_input(raw: str) -> str:
    """Extract access_token from a callback URL, JSON blob, or raw JWT."""
    text = raw.strip().strip('"').strip("'")
    if text.startswith("Bearer "):
        return text[len("Bearer ") :].strip()
    if "access_token=" in text:
        parsed = urllib.parse.urlparse(text)
        for source in (parsed.fragment, parsed.query):
            if source:
                qs = urllib.parse.parse_qs(source)
                if qs.get("access_token"):
                    return qs["access_token"][0]
    if text.startswith("{"):
        obj = json.loads(text)
        if obj.get("access_token"):
            return obj["access_token"]
    return text


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode JWT payload claims without verifying signature."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


def build_authorize_url(*, prompt: str | None = None) -> str:
    """Build the OIDC implicit-flow authorize URL for mypup.web.public."""
    params: dict[str, str] = {
        "response_type": "id_token token",
        "client_id": CLIENT_ID,
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": secrets.token_urlsafe(16),
        "nonce": secrets.token_urlsafe(16),
        "response_mode": "fragment",
    }
    if prompt:
        params["prompt"] = prompt
    return f"{OIDC_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


class MyPupApiClient:
    """Read-only async client for MyPup."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        session_data: MyPupSessionData | None = None,
    ) -> None:
        self._session = session
        self.session_data = session_data or MyPupSessionData()

    async def silent_renew_token(self) -> MyPupSessionData:
        """Use login.mypup.app cookies with prompt=none to obtain a fresh access_token."""
        if not self.session_data.auth_cookies:
            raise MyPupAuthError("No login.mypup.app session cookies available for silent renewal")

        url = build_authorize_url(prompt="none")
        cookie_header = "; ".join(
            f"{k}={v}" for k, v in self.session_data.auth_cookies.items()
        )
        try:
            async with self._session.get(
                url,
                headers={"Cookie": cookie_header},
                allow_redirects=False,
            ) as resp:
                # Capture any sliding/refreshed cookies returned by login.mypup.app
                for morsel in resp.cookies.values():
                    if morsel.value:
                        self.session_data.auth_cookies[morsel.key] = morsel.value

                if resp.status not in (301, 302, 303, 307, 308):
                    raise MyPupAuthError(
                        f"Silent renewal failed with HTTP {resp.status}; re-authentication required"
                    )

                location = resp.headers.get("Location", "")
        except aiohttp.ClientError as err:
            raise MyPupApiError(f"Network error during silent renewal: {err}") from err

        parsed = urllib.parse.urlparse(location)
        qs = urllib.parse.parse_qs(parsed.fragment or parsed.query)

        if qs.get("error"):
            raise MyPupAuthError(
                f"Silent renewal error: {qs['error'][0]} (re-authentication required)"
            )

        access_token = (qs.get("access_token") or [""])[0]
        if not access_token:
            raise MyPupAuthError("Silent renewal did not return an access_token")

        expires_in = float((qs.get("expires_in") or ["3600"])[0])
        exp_claim = decode_jwt_claims(access_token).get("exp")
        expires_at = (
            float(exp_claim) - 60
            if isinstance(exp_claim, (int, float))
            else time.time() + expires_in - 60
        )

        self.session_data.access_token = access_token
        self.session_data.expires_at = expires_at
        return self.session_data

    async def _ensure_valid_token(self) -> str:
        if (
            not self.session_data.access_token
            or time.time() >= self.session_data.expires_at
        ):
            if self.session_data.auth_cookies:
                await self.silent_renew_token()
            elif not self.session_data.access_token:
                raise MyPupAuthError("Client is not authenticated")
        return self.session_data.access_token

    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._ensure_valid_token()
        url = f"{API_BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "mypup-device-type": "WebDesktop",
        }
        async with self._session.post(url, headers=headers, json=payload or {}) as resp:
            if resp.status == 401:
                await self.silent_renew_token()
                headers["Authorization"] = f"Bearer {self.session_data.access_token}"
                async with self._session.post(url, headers=headers, json=payload or {}) as retry:
                    if retry.status == 401:
                        raise MyPupAuthError("Unauthorized after silent token renewal")
                    retry.raise_for_status()
                    data = await retry.json()
            elif resp.status >= 400:
                body = await resp.text()
                raise MyPupApiError(f"API error {resp.status} on {path}: {body}")
            else:
                data = await resp.json()

        if not data.get("isSuccess", True):
            _LOGGER.error("MyPup API failure on %s: %s", path, data)
            raise MyPupApiError(f"MyPup API returned failure on {path}: {data.get('resultCode')}")
        return data

    def _user_uid(self) -> str:
        uid = decode_jwt_claims(self.session_data.access_token).get("sub")
        if not uid:
            raise MyPupAuthError("Access token missing 'sub' (userUid) claim")
        return uid

    async def query_account_details(self) -> dict[str, Any]:
        """Fetch user account details."""
        return await self._post("/Account/QueryAccountDetails", {"userUid": self._user_uid()})

    async def query_main_pickup_point(self) -> dict[str, Any]:
        """Fetch the user's primary Pick Up Point and mail code."""
        return await self._post(
            "/PickUpPoints/QueryAccountMainPickUpPoint", {"userUid": self._user_uid()}
        )

    async def query_shipments(self, page_no: int = 1, page_size: int = 25) -> dict[str, Any]:
        """Fetch user shipments/parcels."""
        return await self._post(
            "/Logistics/QueryShipments",
            {
                "authToken": None,
                "dispatcherUids": [],
                "pageNo": page_no,
                "pageSize": page_size,
                "pageSkip": (page_no - 1) * page_size,
                "ignoreTotal": False,
                "types": [
                    "DispatcherFixedReservation",
                    "UserFixedReservation",
                    "UserExchangeShipment",
                    "ReceiveShipment",
                    "DispatchShipment",
                ],
                "includeShipmentChain": True,
                "filterTransferMethods": None,
                "filterUserUid": "cauthusr",
                "filterPupUid": None,
                "filterIsPupUidBookedOnly": False,
                "filterStateCodes": None,
                "filterUpdatedSince": None,
                "filterPriorShipments": None,
                "filterPostShipments": None,
                "filterPostShipmentTypes": None,
                "filterPriorShipmentTypes": None,
                "shipmentUids": None,
                "sortOrder": "CreatedDesc",
                "filterFromUserUid": None,
                "filterToUserUid": None,
                "filterReferences": None,
                "objectTypeUids": None,
                "filterToUserMinCount": None,
                "allowDirtyRead": True,
            },
        )

    async def query_shipment_actions(self, shipment_uid: str) -> dict[str, Any]:
        """Fetch available actions for a shipment (read-only)."""
        return await self._post(
            "/Logistics/QueryShipmentActions",
            {"shipmentUid": shipment_uid, "userUid": self._user_uid(), "userRole": "EndUser"},
        )

    async def query_shipment_access_config(self, shipment_uid: str) -> dict[str, Any]:
        """Fetch pickup PIN/QR config for a shipment (read-only)."""
        return await self._post(
            "/Logistics/QueryShipmentAccessConfig",
            {"shipmentUid": shipment_uid, "userUid": self._user_uid()},
        )

    async def unlock_shipment_locker(self, shipment_uid: str) -> dict[str, Any]:
        """Request locker unlock for a shipment ready for pickup."""
        payload = {
            "shipmentUid": shipment_uid,
            "openForType": "Default",
            "accessCode": None,
            "authToken": None,
            "remarks": "user_details_web",
        }
        _LOGGER.info("Calling MyPup UnlockShipmentLocker for shipmentUid=%s", shipment_uid)
        data = await self._post("/Logistics/UnlockShipmentLocker", payload)
        _LOGGER.info(
            "MyPup UnlockShipmentLocker response for shipmentUid=%s: isSuccess=%s, resultCode=%s, exception=%s, data=%s",
            shipment_uid,
            data.get("isSuccess"),
            data.get("resultCode"),
            data.get("exception"),
            data,
        )
        return data
