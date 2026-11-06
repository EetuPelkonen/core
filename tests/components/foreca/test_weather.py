"""Test the Foreca weather platform."""

from dataclasses import replace
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.weather import (
    DOMAIN as WEATHER_DOMAIN,
    SERVICE_GET_FORECASTS,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import init_integration

ENTITY_ID = "weather.helsinki"


@pytest.mark.usefixtures("mock_foreca_client")
async def test_weather(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the state of the weather entity."""
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("mock_foreca_client")
@pytest.mark.parametrize("forecast_type", ["daily", "hourly"])
async def test_forecast(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
    forecast_type: str,
) -> None:
    """Test the daily and hourly forecasts."""
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        WEATHER_DOMAIN,
        SERVICE_GET_FORECASTS,
        {ATTR_ENTITY_ID: ENTITY_ID, "type": forecast_type},
        blocking=True,
        return_response=True,
    )
    assert response == snapshot


@pytest.mark.parametrize(
    ("forecast_type", "mocked_method", "undated"),
    [
        ("daily", "forecast_daily", {"date": None}),
        ("hourly", "forecast_hourly", {"time": None}),
    ],
)
async def test_forecast_without_a_time_is_dropped(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
    forecast_type: str,
    mocked_method: str,
    undated: dict[str, None],
) -> None:
    """Test that a forecast entry without a date or time is left out."""
    mocked = getattr(mock_foreca_client, mocked_method)
    mocked.return_value = [replace(mocked.return_value[0], **undated)]
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        WEATHER_DOMAIN,
        SERVICE_GET_FORECASTS,
        {ATTR_ENTITY_ID: ENTITY_ID, "type": forecast_type},
        blocking=True,
        return_response=True,
    )
    assert response == {ENTITY_ID: {"forecast": []}}


@pytest.mark.usefixtures("mock_foreca_client")
async def test_daily_forecast_lands_on_the_right_local_day(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a daily forecast keeps its date in a timezone west of UTC.

    Anchoring to midnight UTC would put the forecast on the previous day for
    anyone west of it.
    """
    await hass.config.async_set_time_zone("America/Los_Angeles")
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        WEATHER_DOMAIN,
        SERVICE_GET_FORECASTS,
        {ATTR_ENTITY_ID: ENTITY_ID, "type": "daily"},
        blocking=True,
        return_response=True,
    )
    first = response[ENTITY_ID]["forecast"][0]
    timestamp = dt_util.parse_datetime(first["datetime"])
    assert timestamp is not None
    # The date has to survive being rendered where Home Assistant is, which is
    # what midnight UTC would break.
    assert dt_util.as_local(timestamp).date() == date(2026, 11, 6)
