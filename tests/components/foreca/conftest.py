"""Common fixtures for the Foreca tests."""

from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

from pyforeca import CurrentWeather, DailyForecast, HourlyForecast, Location
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_load_json_object_fixture

from homeassistant.components.foreca.const import DOMAIN, SUBENTRY_TYPE_LOCATION
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.foreca.async_setup_entry", return_value=None
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
async def mock_foreca_client(hass: HomeAssistant) -> AsyncGenerator[MagicMock]:
    """Mock the Foreca API client with responses recorded from the live API."""
    location = await async_load_json_object_fixture(hass, "location.json", DOMAIN)
    current = await async_load_json_object_fixture(hass, "current.json", DOMAIN)
    hourly = await async_load_json_object_fixture(hass, "forecast_hourly.json", DOMAIN)
    daily = await async_load_json_object_fixture(hass, "forecast_daily.json", DOMAIN)
    with (
        patch(
            "homeassistant.components.foreca.ForecaApiClient",
            autospec=True,
        ) as client_cls,
        patch(
            "homeassistant.components.foreca.config_flow.ForecaApiClient",
            new=client_cls,
        ),
    ):
        client = client_cls.return_value
        client.location_info = AsyncMock(return_value=Location.from_api(location))
        client.current = AsyncMock(
            return_value=CurrentWeather.from_api(current["current"])
        )
        client.forecast_hourly = AsyncMock(
            return_value=[HourlyForecast.from_api(item) for item in hourly["forecast"]]
        )
        client.forecast_daily = AsyncMock(
            return_value=[DailyForecast.from_api(item) for item in daily["forecast"]]
        )
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry with one location subentry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Foreca",
        entry_id="01JZ4Q1F0RECA0000000000000",
        data={CONF_API_KEY: "test-key"},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_LATITUDE: 60.17, CONF_LONGITUDE: 24.94},
                subentry_id="01JZ4Q1F0RECALOCATION000001",
                subentry_type=SUBENTRY_TYPE_LOCATION,
                title="Helsinki",
                unique_id="60.17-24.94",
            )
        ],
    )
