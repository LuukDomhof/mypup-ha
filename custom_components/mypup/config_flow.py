"""Config flow for MyPup integration."""

from __future__ import annotations

import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    MyPupApiClient,
    MyPupApiError,
    MyPupAuthError,
    MyPupSessionData,
    build_authorize_url,
    decode_jwt_claims,
    extract_access_token_from_input,
    parse_cookie_input,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_COOKIES,
    CONF_EXPIRES_AT,
    CONF_FETCH_ACCESS_CODES,
    CONF_SCAN_INTERVAL,
    CONF_SHIPMENTS_LIMIT,
    DEFAULT_FETCH_ACCESS_CODES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_SHIPMENTS_LIMIT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _build_options_schema(options: dict[str, Any]) -> vol.Schema:
    """Build the options schema using numeric input boxes (no sliders)."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=60,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Required(
                CONF_SHIPMENTS_LIMIT,
                default=options.get(CONF_SHIPMENTS_LIMIT, DEFAULT_SHIPMENTS_LIMIT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5,
                    max=100,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_FETCH_ACCESS_CODES,
                default=options.get(CONF_FETCH_ACCESS_CODES, DEFAULT_FETCH_ACCESS_CODES),
            ): selector.BooleanSelector(),
        }
    )


class MyPupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MyPup."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None
        self._pending_title: str = "MyPup"
        self._pending_data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MyPupOptionsFlowHandler:
        """Get the options flow for this handler."""
        return MyPupOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose between persistent Cookie auth or short-lived Token auth."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["cookie", "token"],
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle re-authentication when cookies/tokens expire."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return self.async_show_menu(
            step_id="user",
            menu_options=["cookie", "token"],
        )

    async def async_step_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Authenticate using login.mypup.app session cookies (recommended)."""
        errors: dict[str, str] = {}
        auth_url = build_authorize_url()

        if user_input is not None:
            raw_cookies = (user_input.get("auth_cookies") or "").strip()
            cookies = parse_cookie_input(raw_cookies)
            session = async_get_clientsession(self.hass)
            client = MyPupApiClient(
                session,
                session_data=MyPupSessionData(auth_cookies=cookies),
            )

            try:
                if not cookies:
                    raise MyPupAuthError("No cookies provided")
                await client.silent_renew_token()
                return await self._finish_auth(client)
            except MyPupAuthError as err:
                _LOGGER.warning("MyPup cookie auth error: %s", err)
                errors["base"] = "invalid_auth"
            except MyPupApiError as err:
                _LOGGER.warning("MyPup API error during cookie auth: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error in MyPup cookie step")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="cookie",
            data_schema=vol.Schema(
                {
                    vol.Required("auth_cookies"): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    )
                }
            ),
            description_placeholders={"auth_url": auth_url},
            errors=errors,
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Authenticate using a short-lived access_token."""
        errors: dict[str, str] = {}
        auth_url = build_authorize_url()

        if user_input is not None:
            raw_token = (user_input.get("access_token") or "").strip()
            access_token = extract_access_token_from_input(raw_token) if raw_token else ""
            exp = decode_jwt_claims(access_token).get("exp") if access_token else None
            expires_at = (
                float(exp) - 60
                if isinstance(exp, (int, float))
                else (time.time() + 3000 if access_token else 0.0)
            )
            session = async_get_clientsession(self.hass)
            client = MyPupApiClient(
                session,
                session_data=MyPupSessionData(
                    access_token=access_token,
                    expires_at=expires_at,
                ),
            )

            try:
                if not access_token:
                    raise MyPupAuthError("No access_token provided")
                return await self._finish_auth(client)
            except MyPupAuthError as err:
                _LOGGER.warning("MyPup token auth error: %s", err)
                errors["base"] = "invalid_auth"
            except MyPupApiError as err:
                _LOGGER.warning("MyPup API error during token auth: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error in MyPup token step")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema(
                {
                    vol.Required("access_token"): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={
                "auth_url": auth_url,
                "console_cmd": (
                    "copy(JSON.parse(sessionStorage.getItem("
                    "'oidc.user:https://login.mypup.app:mypup.web.public'"
                    ")).access_token)"
                ),
            },
            errors=errors,
        )

    async def _finish_auth(self, client: MyPupApiClient) -> FlowResult:
        """Validate account details and route to reauth completion or initial options."""
        account = await client.query_account_details()
        details = account.get("details", {})
        user_uid = details.get("userUid") or details.get("emailAddress") or "mypup"
        title = details.get("fullName") or details.get("mainPupName") or "MyPup"

        new_data = {
            CONF_ACCESS_TOKEN: client.session_data.access_token,
            CONF_EXPIRES_AT: client.session_data.expires_at,
            CONF_AUTH_COOKIES: client.session_data.auth_cookies,
        }

        if self._reauth_entry:
            self.hass.config_entries.async_update_entry(
                self._reauth_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        await self.async_set_unique_id(user_uid)
        self._abort_if_unique_id_configured()

        self._pending_title = title
        self._pending_data = new_data
        return await self.async_step_initial_options()

    async def async_step_initial_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow configuring polling and parcel options during initial setup."""
        if user_input is not None:
            options = {
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                CONF_SHIPMENTS_LIMIT: int(user_input[CONF_SHIPMENTS_LIMIT]),
                CONF_FETCH_ACCESS_CODES: bool(user_input[CONF_FETCH_ACCESS_CODES]),
            }
            return self.async_create_entry(
                title=self._pending_title,
                data=self._pending_data,
                options=options,
            )

        return self.async_show_form(
            step_id="initial_options",
            data_schema=_build_options_schema({}),
        )


class MyPupOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle MyPup integration options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage MyPup options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_SHIPMENTS_LIMIT: int(user_input[CONF_SHIPMENTS_LIMIT]),
                    CONF_FETCH_ACCESS_CODES: bool(user_input[CONF_FETCH_ACCESS_CODES]),
                },
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_build_options_schema(self._config_entry.options),
        )
