"""Constants for the MyPup integration."""

from datetime import timedelta

DOMAIN = "mypup"

OIDC_DISCOVERY_URL = "https://login.mypup.app/.well-known/openid-configuration"
OIDC_AUTHORIZE_URL = "https://login.mypup.app/connect/authorize"

API_BASE_URL = "https://api-prop.mypup.app"

CLIENT_ID = "mypup.web.public"
REDIRECT_URI = "https://mypup.app/Login/callback"
SCOPES = "openid profile roles proprietary_api"

CONF_ACCESS_TOKEN = "access_token"
CONF_EXPIRES_AT = "expires_at"
CONF_AUTH_COOKIES = "auth_cookies"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_SHIPMENTS_LIMIT = "shipments_limit"
CONF_FETCH_ACCESS_CODES = "fetch_access_codes"

DEFAULT_SCAN_INTERVAL_MINUTES = 5
DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)
DEFAULT_SHIPMENTS_LIMIT = 25
DEFAULT_FETCH_ACCESS_CODES = True

STATE_READY_FOR_PICKUP = "ReadyForPickup"
INCOMING_STATES = frozenset(
    {
        "Registered",
        "Arrived",
        "WaitForLocker",
        "LockerAssigned",
    }
)

EVENT_PARCEL_INCOMING = "mypup_parcel_incoming"
EVENT_PARCEL_READY = "mypup_parcel_ready"
