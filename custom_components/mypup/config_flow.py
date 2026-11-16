"""Config flow for MyPup integration."""

from __future__ import annotations

import time
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
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


class MyPupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MyPup."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

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
        """Handle the initial step."""
        return await self._async_handle_auth_step("user", user_input)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle re-authentication when cookies/tokens expire."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm re-authentication."""
        return await self._async_handle_auth_step("reauth_confirm", user_input)

    async def _async_handle_auth_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        auth_url = build_authorize_url()

        if user_input is not None:
            raw_cookies = (user_input.get("auth_cookies") or "").strip()
            raw_token = (user_input.get("access_token") or "").strip()

            session = async_get_clientsession(self.hass)
            cookies = parse_cookie_input(raw_cookies)
            access_token = extract_access_token_from_input(raw_token) if raw_token else ""
            exp = decode_jwt_claims(access_token).get("exp") if access_token else None
            expires_at = (
                float(exp) - 60
                if isinstance(exp, (int, float))
                else (time.time() + 3000 if access_token else 0.0)
            )

            session_data = MyPupSessionData(
                access_token=access_token,
                expires_at=expires_at,
                auth_cookies=cookies,
            )
            client = MyPupApiClient(session, session_data=session_data)

            try:
                if cookies and not access_token:
                    await client.silent_renew_token()
                elif not cookies and not access_token:
                    raise MyPupAuthError("Provide login.mypup.app cookies or an access_token")

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

                return self.async_create_entry(title=title, data=new_data)
            except MyPupAuthError:
                errors["base"] = "invalid_auth"
            except MyPupApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Optional("auth_cookies", default=""): str,
                vol.Optional("access_token", default=""): str,
            }
        )

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders={"auth_url": auth_url},
            errors=errors,
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
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Optional(
                    CONF_SHIPMENTS_LIMIT,
                    default=options.get(CONF_SHIPMENTS_LIMIT, DEFAULT_SHIPMENTS_LIMIT),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=100)),
                vol.Optional(
                    CONF_FETCH_ACCESS_CODES,
                    default=options.get(
                        CONF_FETCH_ACCESS_CODES, DEFAULT_FETCH_ACCESS_CODES
                    ),
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
