"""Config flow for the Foreca integration."""

from collections.abc import Mapping
import logging
from typing import Any, override

import probatio
from pyforeca import (
    ForecaApiClient,
    ForecaAuthError,
    ForecaError,
    Location,
    format_location,
)

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import LocationSelector

from .const import DOMAIN, SUBENTRY_TYPE_LOCATION
from .coordinator import ForecaConfigEntry

_LOGGER = logging.getLogger(__name__)

API_KEY_SCHEMA = probatio.Schema({probatio.Required(CONF_API_KEY): str})


async def _async_check_location(
    hass: HomeAssistant, api_key: str, latitude: float, longitude: float
) -> tuple[dict[str, str], Location | None]:
    """Check a key against a location, returning form errors if any."""
    client = ForecaApiClient(api_key, session=async_get_clientsession(hass))
    location = format_location(lon=longitude, lat=latitude)
    try:
        info = await client.location_info(location)
        await client.current(location)
    except ForecaAuthError:
        return {"base": "invalid_auth"}, None
    except ForecaError:
        return {"base": "cannot_connect"}, None
    except Exception:
        _LOGGER.exception("Unexpected error validating Foreca API key")
        return {"base": "unknown"}, None
    return {}, info


class ForecaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Foreca."""

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the API key, and check it against the home location."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_API_KEY: user_input[CONF_API_KEY]})
            errors, info = await _async_check_location(
                self.hass,
                user_input[CONF_API_KEY],
                self.hass.config.latitude,
                self.hass.config.longitude,
            )
            if not errors:
                return self.async_create_entry(
                    title="Foreca",
                    data={CONF_API_KEY: user_input[CONF_API_KEY]},
                    subentries=[
                        ConfigSubentryData(
                            data={
                                CONF_LATITUDE: self.hass.config.latitude,
                                CONF_LONGITUDE: self.hass.config.longitude,
                            },
                            subentry_type=SUBENTRY_TYPE_LOCATION,
                            title=(info.name if info else None) or "Foreca",
                            unique_id=(
                                f"{self.hass.config.latitude}-"
                                f"{self.hass.config.longitude}"
                            ),
                        )
                    ],
                )

        return self.async_show_form(
            step_id="user", data_schema=API_KEY_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Ask for a new API key once the current one is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new API key after a rejection."""
        return await self._async_step_replace_key(
            "reauth_confirm", self._get_reauth_entry(), user_input
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user replace the API key."""
        return await self._async_step_replace_key(
            "reconfigure", self._get_reconfigure_entry(), user_input
        )

    async def _async_step_replace_key(
        self,
        step_id: str,
        entry: ForecaConfigEntry,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Check a new API key against the first location, then store it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_API_KEY: user_input[CONF_API_KEY]})
            locations = entry.get_subentries_of_type(SUBENTRY_TYPE_LOCATION)
            if locations:
                latitude = locations[0].data[CONF_LATITUDE]
                longitude = locations[0].data[CONF_LONGITUDE]
            else:
                latitude = self.hass.config.latitude
                longitude = self.hass.config.longitude
            errors, _ = await _async_check_location(
                self.hass, user_input[CONF_API_KEY], latitude, longitude
            )
            if not errors:
                if (
                    not self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_API_KEY: user_input[CONF_API_KEY]},
                    )
                    or not entry.update_listeners
                ):
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_update_and_abort(entry)

        return self.async_show_form(
            step_id=step_id, data_schema=API_KEY_SCHEMA, errors=errors
        )

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ForecaConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types this integration supports."""
        return {SUBENTRY_TYPE_LOCATION: LocationSubentryFlowHandler}


class LocationSubentryFlowHandler(ConfigSubentryFlow):
    """Handle adding a location to an existing Foreca entry."""

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for a location to forecast."""
        errors: dict[str, str] = {}
        entry = self._get_entry()
        if user_input is not None:
            latitude = user_input[CONF_LOCATION][CONF_LATITUDE]
            longitude = user_input[CONF_LOCATION][CONF_LONGITUDE]
            unique = f"{latitude}-{longitude}"
            if any(
                subentry.unique_id == unique
                for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_LOCATION)
            ):
                return self.async_abort(reason="already_configured")

            errors, info = await _async_check_location(
                self.hass, entry.data[CONF_API_KEY], latitude, longitude
            )
            if not errors:
                return self.async_create_entry(
                    title=(info.name if info else None) or "Foreca",
                    data={CONF_LATITUDE: latitude, CONF_LONGITUDE: longitude},
                    unique_id=unique,
                )

        return self.async_show_form(
            step_id="location",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_LOCATION,
                        default={
                            CONF_LATITUDE: self.hass.config.latitude,
                            CONF_LONGITUDE: self.hass.config.longitude,
                        },
                    ): LocationSelector()
                }
            ),
            errors=errors,
        )

    async_step_user = async_step_location
