"""Test the Foreca weather platform."""

from datetime import date
from unittest.mock import MagicMock, patch

from pyforeca import DailyForecast, HourlyForecast, Location
import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.foreca.const import DOMAIN
from homeassistant.components.foreca.services import SERVICE_GET_FORECASTS_EXTRA
from homeassistant.components.weather import (
    DOMAIN as WEATHER_DOMAIN,
    SERVICE_GET_FORECASTS,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import (
    METRIC_SYSTEM,
    US_CUSTOMARY_SYSTEM,
    UnitSystem,
)

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
        ("daily", "forecast_daily", [DailyForecast(date=None)]),
        ("hourly", "forecast_hourly", [HourlyForecast(time=None)]),
    ],
)
async def test_forecast_without_a_time_is_dropped(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
    forecast_type: str,
    mocked_method: str,
    undated: list[DailyForecast] | list[HourlyForecast],
) -> None:
    """Test that a forecast entry without a date or time is left out."""
    getattr(mock_foreca_client, mocked_method).return_value = undated
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
    assert dt_util.as_local(timestamp).date() == date(2026, 9, 2)


@pytest.mark.usefixtures("mock_foreca_client")
@pytest.mark.parametrize("forecast_type", ["daily", "hourly"])
@pytest.mark.parametrize(
    "unit_system",
    [
        pytest.param(METRIC_SYSTEM, id="metric"),
        pytest.param(US_CUSTOMARY_SYSTEM, id="us_customary"),
    ],
)
async def test_forecasts_extra(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
    forecast_type: str,
    unit_system: UnitSystem,
) -> None:
    """Test the extra forecast values in the entity's units."""
    hass.config.units = unit_system
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_FORECASTS_EXTRA,
        {ATTR_ENTITY_ID: ENTITY_ID, "type": forecast_type},
        blocking=True,
        return_response=True,
    )
    assert response == snapshot


@pytest.mark.parametrize(
    ("forecast_type", "mocked_method", "undated"),
    [
        ("daily", "forecast_daily", [DailyForecast(date=None)]),
        ("hourly", "forecast_hourly", [HourlyForecast(time=None)]),
    ],
)
async def test_forecasts_extra_without_a_time_is_dropped(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
    forecast_type: str,
    mocked_method: str,
    undated: list[DailyForecast] | list[HourlyForecast],
) -> None:
    """Test that a forecast entry without a date or time is left out."""
    getattr(mock_foreca_client, mocked_method).return_value = undated
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_FORECASTS_EXTRA,
        {ATTR_ENTITY_ID: ENTITY_ID, "type": forecast_type},
        blocking=True,
        return_response=True,
    )
    assert response == {ENTITY_ID: {"forecast": []}}


@pytest.mark.usefixtures("mock_foreca_client")
async def test_moon_times_are_at_the_location(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test moonrise and moonset are read in the location's time zone.

    The API gives them as times of day where the location is, which differs
    from where Home Assistant is.
    """
    await hass.config.async_set_time_zone("America/Los_Angeles")
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_FORECASTS_EXTRA,
        {ATTR_ENTITY_ID: ENTITY_ID, "type": "daily"},
        blocking=True,
        return_response=True,
    )
    assert [
        (day["moon_phase"], day["moonrise"], day["moonset"])
        for day in response[ENTITY_ID]["forecast"]
    ] == [
        (128, "2026-09-02T16:51:03+00:00", "2026-09-02T03:43:27+00:00"),
        (140, None, "2026-09-03T04:58:12+00:00"),
    ]


async def test_moon_times_without_a_time_zone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
) -> None:
    """Test moonrise and moonset are left out when the location has no time zone."""
    mock_foreca_client.location_info.return_value = Location(timezone=None)
    with patch("homeassistant.components.foreca.PLATFORMS", [Platform.WEATHER]):
        await init_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_FORECASTS_EXTRA,
        {ATTR_ENTITY_ID: ENTITY_ID, "type": "daily"},
        blocking=True,
        return_response=True,
    )
    first = response[ENTITY_ID]["forecast"][0]
    assert (first["moon_phase"], first["moonrise"], first["moonset"]) == (
        128,
        None,
        None,
    )
