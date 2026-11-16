"""Standalone read-only CLI to verify MyPup login, shipments, and shipment details.

Strictly read-only: only queries account details, main pickup point, shipments,
shipment details, available actions, and pickup access config.
Never triggers locker unlock (/Logistics/UnlockShipmentLocker) or state-changing endpoints.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

OIDC_DISCOVERY_URL = "https://login.mypup.app/.well-known/openid-configuration"
API_BASE_URL = "https://api-prop.mypup.app"
WEB_CLIENT_ID = "mypup.web.public"
WEB_REDIRECT_URI = "https://mypup.app/Login/callback"
WEB_SCOPES = "openid profile roles proprietary_api"
TOKEN_FILE = Path(__file__).with_name(".mypup_tokens.json")


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {err.code} from {url}: {body}") from err


def _http_form(url: str, form_body: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(form_body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {err.code} from {url}: {body}") from err


def check_oidc_refresh_support() -> None:
    """Inspect OIDC discovery metadata and test code+PKCE+offline_access on mypup.web.public."""
    oidc = _http_json(OIDC_DISCOVERY_URL)
    print("\n--- OIDC Discovery ---")
    for key in (
        "grant_types_supported",
        "response_types_supported",
        "scopes_supported",
        "token_endpoint_auth_methods_supported",
        "device_authorization_endpoint",
    ):
        print(f"  {key}: {oidc.get(key)}")

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": WEB_CLIENT_ID,
            "scope": f"{WEB_SCOPES} offline_access",
            "redirect_uri": WEB_REDIRECT_URI,
            "state": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    url = f"{oidc['authorization_endpoint']}?{params}"
    print(f"\nTest Authorization Code + PKCE URL:\n  {url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    raw = input("Paste the redirected URL (containing ?code=...) or press Enter to skip: ").strip()
    if not raw:
        return
    parsed = urllib.parse.urlparse(raw)
    code = urllib.parse.parse_qs(parsed.query).get("code", [raw])[0]
    tokens = _http_form(
        oidc["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "client_id": WEB_CLIENT_ID,
            "code": code,
            "redirect_uri": WEB_REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    print("\nToken response keys:", list(tokens.keys()))
    if tokens.get("refresh_token"):
        print("SUCCESS: refresh_token received! Background refresh is supported.")
    else:
        print("No refresh_token in response.")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def test_silent_renew() -> None:
    """Test prompt=none silent token renewal using login.mypup.app session cookies."""
    saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8")) if TOKEN_FILE.exists() else {}
    cookie_header = saved.get("cookie_header", "")
    if not cookie_header:
        print("\nPaste the 'Cookie' request header for login.mypup.app (from DevTools -> Network -> authorize -> Request Headers -> cookie):")
        cookie_header = input("> ").strip()
    if not cookie_header:
        raise RuntimeError("No Cookie header provided.")

    oidc = _http_json(OIDC_DISCOVERY_URL)
    params = urllib.parse.urlencode(
        {
            "response_type": "id_token token",
            "client_id": WEB_CLIENT_ID,
            "scope": WEB_SCOPES,
            "redirect_uri": WEB_REDIRECT_URI,
            "state": secrets.token_urlsafe(16),
            "nonce": secrets.token_urlsafe(16),
            "response_mode": "fragment",
            "prompt": "none",
        }
    )
    url = f"{oidc['authorization_endpoint']}?{params}"
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(url, headers={"Cookie": cookie_header}, method="GET")

    try:
        resp = opener.open(req, timeout=20)
        status = resp.status
        location = resp.headers.get("Location", "")
    except urllib.error.HTTPError as err:
        status = err.code
        location = err.headers.get("Location", "")

    print(f"\nSilent renew HTTP status: {status}")
    if not location:
        raise RuntimeError("No Location redirect header returned; cookies may be expired or invalid.")

    parsed = urllib.parse.urlparse(location)
    qs = urllib.parse.parse_qs(parsed.fragment or parsed.query)
    if qs.get("error"):
        raise RuntimeError(f"Silent renew returned error: {qs['error'][0]}")

    access_token = (qs.get("access_token") or [""])[0]
    if not access_token:
        raise RuntimeError("Redirect Location did not contain access_token.")

    TOKEN_FILE.write_text(
        json.dumps({"access_token": access_token, "cookie_header": cookie_header}, indent=2),
        encoding="utf-8",
    )
    user_uid = _decode_jwt_claims(access_token).get("sub")
    account = api_post("/Account/QueryAccountDetails", access_token, {"userUid": user_uid})
    details = account.get("details", {})
    print(f"SUCCESS! Silently renewed token for: {details.get('fullName')} (PUP: {details.get('mainPupName')})")


def _extract_access_token(user_input: str) -> str:
    text = user_input.strip().strip('"').strip("'")
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


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


def _token_remaining_seconds(token: str) -> int | None:
    exp = _decode_jwt_claims(token).get("exp")
    if isinstance(exp, (int, float)):
        return int(exp - time.time())
    return None


def _read_clipboard() -> str:
    try:
        import pyperclip  # type: ignore

        return pyperclip.paste() or ""
    except Exception:
        return ""


def authenticate(force_prompt: bool = False) -> str:
    if not force_prompt and TOKEN_FILE.exists():
        saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        token = saved.get("access_token", "")
        if token:
            remaining = _token_remaining_seconds(token)
            if remaining is None or remaining > 30:
                mins = f" (~{remaining // 60}m left)" if remaining is not None else ""
                print(f"Using saved access_token from {TOKEN_FILE.name}{mins}.")
                return token
            print("Saved access_token has expired.")

    print("\n--- MyPup Login ---")
    print("Option A (fastest if already signed in on https://mypup.app):")
    print("  Run this in Chrome DevTools Console to copy your token:")
    print("  copy(JSON.parse(sessionStorage.getItem('oidc.user:https://login.mypup.app:mypup.web.public')).access_token)")
    print("\nOption B: Open login page in your browser? (Press 'o' + Enter to open, or paste token / press Enter to read clipboard)")

    raw = input("> ").strip()
    if raw.lower() == "o":
        oidc = _http_json(OIDC_DISCOVERY_URL)
        auth_params = urllib.parse.urlencode(
            {
                "response_type": "id_token token",
                "client_id": WEB_CLIENT_ID,
                "scope": WEB_SCOPES,
                "redirect_uri": WEB_REDIRECT_URI,
                "state": secrets.token_urlsafe(16),
                "nonce": secrets.token_urlsafe(16),
                "response_mode": "fragment",
            }
        )
        auth_url = f"{oidc['authorization_endpoint']}?{auth_params}"
        print(f"\nOpening: {auth_url}\n")
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass
        print("After signing in on mypup.app, copy the token with the DevTools snippet above.")
        raw = input("Paste token (or press Enter to read from clipboard): ").strip()

    if not raw:
        raw = _read_clipboard()
        if not raw:
            raise RuntimeError("Clipboard is empty and no token was pasted.")
        print("Read token from clipboard.")

    access_token = _extract_access_token(raw)
    if not _decode_jwt_claims(access_token).get("sub"):
        raise RuntimeError("Input does not look like a valid MyPup JWT access_token.")

    TOKEN_FILE.write_text(json.dumps({"access_token": access_token}, indent=2), encoding="utf-8")
    print(f"Saved access_token to {TOKEN_FILE.name} (gitignored).")
    return access_token


def api_post(path: str, access_token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _http_json(
        f"{API_BASE_URL}{path}",
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "mypup-device-type": "WebDesktop",
        },
        json_body=payload or {},
    )


def inspect_shipment(item: dict[str, Any], access_token: str, user_uid: str) -> None:
    shipment_uid = item.get("shipmentUid")
    if not shipment_uid:
        print("Selected shipment has no shipmentUid.")
        return

    print(f"\n=== Shipment {item.get('referenceNo')} ({shipment_uid}) ===")
    details_resp = api_post(
        "/Logistics/QueryShipmentDetails",
        access_token,
        {"shipmentUid": shipment_uid, "userUid": user_uid},
    )
    details = details_resp.get("details") or {}
    for key in (
        "referenceNo",
        "description",
        "type",
        "stateCode",
        "stateStart",
        "dateCreated",
        "transferMethod",
        "transferDetails",
        "bookedPupName",
        "bookedLockerName",
    ):
        if details.get(key) is not None:
            print(f"  {key}: {details.get(key)}")

    actions_resp = api_post(
        "/Logistics/QueryShipmentActions",
        access_token,
        {"shipmentUid": shipment_uid, "userUid": user_uid, "userRole": "EndUser"},
    )
    actions_list = actions_resp.get("items") or []
    if actions_list:
        enabled = [k for k, v in actions_list[0].items() if k.startswith("can") and v is True]
        print(f"  enabledActions: {', '.join(enabled) if enabled else 'none'}")

    try:
        access_resp = api_post(
            "/Logistics/QueryShipmentAccessConfig",
            access_token,
            {"shipmentUid": shipment_uid, "userUid": user_uid},
        )
        codes = (access_resp.get("accessConfig") or {}).get("codes") or []
        if codes:
            print("  accessCodes:")
            for c in codes:
                print(f"    - {c.get('usage')} ({c.get('type')}): {c.get('code')}")
    except RuntimeError as err:
        print(f"  accessCodes: unavailable ({err})")


def main() -> None:
    access_token = authenticate()
    user_uid = _decode_jwt_claims(access_token).get("sub")
    if not user_uid:
        raise RuntimeError("Could not find 'sub' (userUid) claim in access_token JWT.")

    try:
        account = api_post("/Account/QueryAccountDetails", access_token, {"userUid": user_uid})
    except RuntimeError as err:
        if "HTTP 401" in str(err):
            print("Token rejected (401); prompting for a fresh token...")
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()
            access_token = authenticate(force_prompt=True)
            user_uid = _decode_jwt_claims(access_token)["sub"]
            account = api_post("/Account/QueryAccountDetails", access_token, {"userUid": user_uid})
        else:
            raise

    details = account.get("details", {})
    print(f"\nSigned in as: {details.get('fullName')} (PUP: {details.get('mainPupName')})")

    pup = api_post("/PickUpPoints/QueryAccountMainPickUpPoint", access_token, {"userUid": user_uid})
    print(f"Mail code:    {pup.get('mailCode')}")

    shipments = api_post(
        "/Logistics/QueryShipments",
        access_token,
        {
            "authToken": None,
            "dispatcherUids": [],
            "pageNo": 1,
            "pageSize": 25,
            "pageSkip": 0,
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
    items = shipments.get("items", [])
    print(f"\nShipments ({len(items)}):")
    for idx, item in enumerate(items, start=1):
        locker = item.get("transferDetails") or "-"
        print(
            f"  [{idx:>2}] [{item.get('stateCode')}] {item.get('referenceNo')} "
            f"| {item.get('description') or 'No description'} "
            f"| PUP: {item.get('bookedPupName')} (Locker: {locker})"
        )

    while items:
        choice = input("\nSelect a shipment number to inspect (or Enter to quit): ").strip()
        if not choice:
            break
        if not choice.isdigit() or not (1 <= int(choice) <= len(items)):
            print(f"Please enter a number between 1 and {len(items)}.")
            continue
        inspect_shipment(items[int(choice) - 1], access_token, user_uid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MyPup read-only CLI")
    parser.add_argument(
        "--check-oidc",
        action="store_true",
        help="Check OIDC discovery metadata and test refresh_token support on mypup.web.public",
    )
    parser.add_argument(
        "--test-renew",
        action="store_true",
        help="Test prompt=none silent token renewal using login.mypup.app cookies",
    )
    args = parser.parse_args()
    if args.check_oidc:
        check_oidc_refresh_support()
    elif args.test_renew:
        test_silent_renew()
    else:
        main()
