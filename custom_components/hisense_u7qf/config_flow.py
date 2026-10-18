"""Config flow for Hisense VIDAA TV integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow

from .const import (
    CONF_IP_ADDRESS,
    CONF_MAC_ADDRESS,
    DEFAULT_AUTH_PROFILE,
    DEFAULT_USE_SSL,
    DOMAIN,
)
from .flow_certs import CertsFlowMixin
from .flow_discovery import DiscoveryFlowMixin
from .flow_helpers import (
    async_disconnect_existing_client,
    async_discover_device_details,
    async_probe_device_capabilities,
    async_resolve_mac,
    build_entry_options,
    collect_client_auth_data,
)
from .flow_reauth import ReauthFlowMixin
from .options_flow import HisenseVidaaOptionsFlowHandler
from .protocol.pairing import PairingStatusError, async_probe_pairing_challenge
from .u7qf_client import U7QFClient as HisenseTvClient

_LOGGER = logging.getLogger(__name__)


class HisenseVidaaConfigFlow(
    config_entries.ConfigFlow,
    DiscoveryFlowMixin,
    ReauthFlowMixin,
    CertsFlowMixin,
    domain=DOMAIN,
):
    """Handle a config flow for Hisense VIDAA TV."""

    VERSION = 1

    def __init__(self) -> None:
        self.ip_address: str | None = None
        self.mac_address: str | None = None
        self.auth_profile: str = DEFAULT_AUTH_PROFILE
        self.certfile: str | None = None
        self.keyfile: str | None = None
        self.use_ssl: bool = DEFAULT_USE_SSL
        self.client: HisenseTvClient | None = None
        self.discovered_title: str | None = None
        self.model: str | None = None
        self.manufacturer: str | None = None
        self.sw_version: str | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None
        self._pairing_error: str | None = None
        self.experimental_model = False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return HisenseVidaaOptionsFlowHandler()

    async def _async_discover_device_name(self) -> None:
        """Discovers friendly device name and model info from UPnP/DLNA."""
        details = await async_discover_device_details(self.hass, self.client, self.ip_address)
        self.discovered_title = details["title"]
        if details["model"]:
            self.model = details["model"]
        if details["manufacturer"]:
            self.manufacturer = details["manufacturer"]
        if details["sw_version"]:
            self.sw_version = details["sw_version"]

    async def _async_probe_device_capabilities(self) -> None:
        """Probe TV capabilities (picture/sound menus) to set intelligent default options."""
        await async_probe_device_capabilities(self.hass, self.client, self.ip_address)

    async def _async_disconnect_existing_client(self) -> None:
        """Disconnect any running client for this IP/MAC to avoid MQTT session collision during pairing."""
        # Only ever disconnect the entry being re-paired: a sibling entry that
        # happens to share the IP/MAC must keep its client connected.
        entry_id = self._reauth_entry.entry_id if self._reauth_entry else None
        await async_disconnect_existing_client(
            self.hass, self.ip_address, self.mac_address, entry_id=entry_id
        )

    def _get_client_auth_data(self) -> dict[str, Any]:
        """Collect authentication credentials and device attributes dictionary."""
        return collect_client_auth_data(
            ip_address=self.ip_address,
            auth_profile=self.auth_profile,
            use_ssl=self.use_ssl,
            mac_address=self.mac_address,
            client=self.client,
            certfile=self.certfile,
            keyfile=self.keyfile,
            model=self.model,
            manufacturer=self.manufacturer,
            sw_version=self.sw_version,
        )

    async def _async_init_client_and_auth(
        self, is_reauth: bool = False, reauth_reason: str = "reauth_successful"
    ) -> config_entries.ConfigFlowResult:
        """Helper to initialize client, perform static auth check, and route to PIN or options."""
        self.auth_profile = "legacy"
        if not self._resolve_ssl_certs():
            raise ValueError("Bundled application certificates are missing")
        if not self.mac_address:
            self.mac_address = await async_resolve_mac(self.hass, self.ip_address)

        # Duplicate/unique-id guard MUST run before touching the running client:
        # its AbortFlow must not leave an existing (working) entry disconnected.
        if self.mac_address and self._reauth_entry is None:
            await self.async_set_unique_id(self.mac_address)
            self._abort_if_unique_id_configured()

        await self._async_disconnect_existing_client()
        self.client = HisenseTvClient(
            self.ip_address,
            self.mac_address,
            auth_profile=self.auth_profile,
            certfile=self.certfile if self.use_ssl else None,
            keyfile=self.keyfile if self.use_ssl else None,
            use_ssl=self.use_ssl,
        )
        self.client._loop = self.hass.loop

        await self.client.async_start_auth()

        return await self._async_static_pairing_step(is_reauth, reauth_reason)

    async def _async_static_pairing_step(
        self, is_reauth: bool, reauth_reason: str
    ) -> config_entries.ConfigFlowResult:
        """Probe a static session for a PIN challenge before continuing as before.

        The TV shows a 4-digit code (and pushes it to .../data/authentication)
        only when it does not yet know this client. Already-paired TVs and
        pre-dynamic firmware answer normally, so nothing changes for them - no
        form is shown and the flow continues exactly as it did before.
        """
        try:
            challenged = await async_probe_pairing_challenge(self.client)
        except PairingStatusError as e:
            _LOGGER.warning("[%s] TV pairing dialog %s during challenge probe", self.ip_address, e.status)
            self._pairing_error = "invalid_auth"
            return await self.async_step_auth()

        if not self.client.connected:
            raise ValueError("The TV did not accept the MQTT connection")
        if challenged:
            return await self.async_step_auth()

        # No challenge: behave exactly as today. Drop the probe connection so
        # the remaining steps see the same (unconnected) client as before.
        await self.hass.async_add_executor_job(self.client.disconnect)
        if is_reauth and self._reauth_entry:
            return await self._async_finish_reauth(reason=reauth_reason)
        await self._async_discover_device_name()
        await self._async_probe_device_capabilities()
        return await self.async_step_options()

    # --------------------------------------------------------------------------
    # Flow Steps
    # --------------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle manual user IP configuration step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self.ip_address = user_input[CONF_IP_ADDRESS].strip()
            from .model import old_integration_active
            if old_integration_active(self.hass, self.ip_address):
                return self.async_abort(reason="old_integration_active")
            self.auth_profile = "legacy"
            self.experimental_model = bool(user_input.get("experimental_model", False))
            self.mac_address = await async_resolve_mac(self.hass, self.ip_address)

            if self.auth_profile in ("auto", "legacy"):
                if self._resolve_ssl_certs():
                    try:
                        return await self._async_init_client_and_auth()
                    except AbortFlow:
                        # HA flow control (e.g. duplicate unique_id) must not be
                        # reported as cannot_connect.
                        raise
                    except Exception as e:
                        _LOGGER.warning("[%s] Failed to connect or initiate auth with TV: %s", self.ip_address, e)
                        errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_certs()
            else:
                return await self.async_step_certs()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Optional("experimental_model", default=False): bool,
            }),
            errors=errors,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle PIN code entry step."""
        errors: dict[str, str] = {}
        if self._pairing_error:
            # Surfaced by the static-session challenge probe (TV busy / dialog closed).
            errors["base"] = self._pairing_error
            self._pairing_error = None

        if not self.client:
            if not self.ip_address and self._reauth_entry:
                self.ip_address = self._reauth_entry.data.get(CONF_IP_ADDRESS)
                self.mac_address = self._reauth_entry.data.get(CONF_MAC_ADDRESS)
                self.auth_profile = "legacy"

            if self.ip_address:
                self.client = HisenseTvClient(
                    self.ip_address, self.mac_address, auth_profile=self.auth_profile
                )
                try:
                    await self.client.async_start_auth()
                except Exception as e:
                    _LOGGER.warning("[%s] Failed to connect to TV to show PIN: %s", self.ip_address, e)
                    errors["base"] = "cannot_connect"

        if user_input is not None and self.client:
            pin_code = str(user_input["pin_code"]).strip().replace(" ", "").replace("-", "")
            # F9-leg6: guard ONLY the submit call - a failure afterwards (name
            # discovery, capability probe) must not be reported as a bad PIN.
            try:
                await self.client.async_submit_pin(pin_code)
            except PairingStatusError as e:
                # TV closed the dialog or another remote occupies the slot; the
                # form is re-shown so the pairing can be retried.
                _LOGGER.warning("[%s] TV pairing dialog %s while submitting PIN", self.ip_address, e.status)
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.warning("[%s] Failed to validate PIN or retrieve tokens from TV: %s", self.ip_address, e)
                errors["base"] = "invalid_auth"
            else:
                if self._reauth_entry:
                    return await self._async_finish_reauth(reason="reauth_successful")

                await self._async_discover_device_name()
                await self._async_probe_device_capabilities()
                return await self.async_step_options()

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema({
                vol.Required("pin_code"): str,
            }),
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Allow configuring initial options during setup."""

        if user_input is not None and self.client:
            from .compatibility import runtime_options
            from .model import is_known_model

            if not is_known_model(self.model) and not self.experimental_model:
                await self.hass.async_add_executor_job(self.client.disconnect)
                self.client = None
                return self.async_abort(reason="unsupported_model")
            entry_data = self._get_client_auth_data()
            entry_data["experimental_model"] = self.experimental_model

            await self.hass.async_add_executor_job(self.client.disconnect)
            self.client = None

            return self.async_create_entry(
                title=self.discovered_title or f"Hisense TV ({self.ip_address})",
                data=entry_data,
                options=runtime_options(build_entry_options(user_input, True, False), self.model),
            )

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema({}),
        )

    @callback
    def async_remove(self) -> None:
        """Clean up running flow client when config flow is aborted or closed."""
        if self.client:
            client = self.client
            self.client = None
            if hasattr(self, "hass") and self.hass:
                future = self.hass.async_add_executor_job(client.disconnect)
                future.add_done_callback(self._async_log_remove_exception)
            else:
                client.disconnect()

    @callback
    def _async_log_remove_exception(self, future: Any) -> None:
        """Log a failed async_remove disconnect (the future is otherwise fire-and-forget)."""
        if not future.cancelled() and future.exception() is not None:
            _LOGGER.debug("Error disconnecting flow client during async_remove: %s", future.exception())
