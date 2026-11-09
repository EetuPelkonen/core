"""Data update coordinator for the Foreca integration."""

from dataclasses import dataclass
import logging
from typing import override
from zoneinfo import ZoneInfo

from pyforeca import (
    CurrentWeather,
    DailyForecast,
    ForecaApiClient,
    ForecaAuthError,
    ForecaError,
    HourlyForecast,
    format_location,
)

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DAILY_PERIODS, DOMAIN, HOURLY_PERIODS, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ForecaConfigEntry = ConfigEntry[dict[str, ForecaUpdateCoordinator]]


@dataclass(slots=True)
class ForecaWeatherData:
    """Weather data returned by the Foreca API."""

    current: CurrentWeather
    hourly: list[HourlyForecast]
    daily: list[DailyForecast]


class ForecaUpdateCoordinator(DataUpdateCoordinator[ForecaWeatherData]):
    """Class to manage fetching Foreca data for one location."""

    config_entry: ForecaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ForecaConfigEntry,
        subentry: ConfigSubentry,
        client: ForecaApiClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {subentry.title}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.location = format_location(
            lon=subentry.data[CONF_LONGITUDE], lat=subentry.data[CONF_LATITUDE]
        )
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Foreca",
            entry_type=DeviceEntryType.SERVICE,
        )
        self.time_zone: ZoneInfo | None = None

    @override
    async def _async_setup(self) -> None:
        """Look up the time zone of the location.

        The daily forecast gives moonrise and moonset as times of day at the
        location, which mean nothing without its time zone.
        """
        try:
            location = await self.client.location_info(self.location)
        except ForecaAuthError as err:
            raise ConfigEntryAuthFailed(
                f"The Foreca API rejected the API key: {err}"
            ) from err
        except ForecaError as err:
            raise UpdateFailed(
                f"Error communicating with the Foreca API: {err}"
            ) from err
        if location.timezone:
            self.time_zone = await dt_util.async_get_time_zone(location.timezone)

    @override
    async def _async_update_data(self) -> ForecaWeatherData:
        """Fetch data from the Foreca API."""
        try:
            current = await self.client.current(self.location)
            hourly = await self.client.forecast_hourly(
                self.location, periods=HOURLY_PERIODS, dataset="full"
            )
            daily = await self.client.forecast_daily(
                self.location, periods=DAILY_PERIODS, dataset="full"
            )
        except ForecaAuthError as err:
            raise ConfigEntryAuthFailed(
                f"The Foreca API rejected the API key: {err}"
            ) from err
        except ForecaError as err:
            raise UpdateFailed(
                f"Error communicating with the Foreca API: {err}"
            ) from err

        return ForecaWeatherData(current=current, hourly=hourly, daily=daily)
