"""Test the Foreca config flow."""

from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
from pyforeca import ForecaAuthError, ForecaConnectionError
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components.foreca.const import (
    DOMAIN,
    SUBENTRY_TYPE_LOCATION,
    UPDATE_INTERVAL,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER, ConfigEntryState
from homeassistant.const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import init_integration

USER_INPUT = {CONF_API_KEY: "test-key"}
LOCATION_INPUT = {CONF_LOCATION: {CONF_LATITUDE: 60.17, CONF_LONGITUDE: 24.94}}
SECOND_LOCATION_INPUT = {CONF_LOCATION: {CONF_LATITUDE: 48.86, CONF_LONGITUDE: 2.35}}
ENTITY_ID = "weather.helsinki"


@pytest.mark.usefixtures("mock_setup_entry", "mock_foreca_client")
async def test_full_flow(hass: HomeAssistant) -> None:
    """Test the API key is all the entry needs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Foreca"
    assert result["data"] == {CONF_API_KEY: "test-key"}
    # A new entry starts with the Home Assistant home location, so setting the
    # integration up produces a weather entity without a second step.
    assert [subentry["data"] for subentry in result["subentries"]] == [
        {CONF_LATITUDE: hass.config.latitude, CONF_LONGITUDE: hass.config.longitude}
    ]


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (ForecaAuthError, "invalid_auth"),
        (ForecaConnectionError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_errors_then_recovers(
    hass: HomeAssistant,
    mock_foreca_client: MagicMock,
    exception: type[Exception],
    error: str,
) -> None:
    """Test a bad key keeps the form open, then succeeds once it is fixed."""
    mock_foreca_client.location_info.side_effect = exception
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_foreca_client.location_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_foreca_client")
async def test_add_second_location(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a second location is added to the same entry as a subentry."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_LOCATION),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "location"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], SECOND_LOCATION_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Helsinki"
    assert result["data"] == {CONF_LATITUDE: 48.86, CONF_LONGITUDE: 2.35}


@pytest.mark.usefixtures("mock_foreca_client")
async def test_duplicate_location_aborts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test adding a location that is already configured aborts."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_LOCATION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], LOCATION_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (ForecaAuthError, "invalid_auth"),
        (ForecaConnectionError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_subentry_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
    exception: type[Exception],
    error: str,
) -> None:
    """Test a location the API cannot serve keeps the form open, then succeeds."""
    mock_config_entry.add_to_hass(hass)
    mock_foreca_client.location_info.side_effect = exception

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_LOCATION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], SECOND_LOCATION_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_foreca_client.location_info.side_effect = None
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], SECOND_LOCATION_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry")
async def test_entry_title_falls_back_without_location_name(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
) -> None:
    """Test the subentry title falls back when the API returns no name."""
    mock_config_entry.add_to_hass(hass)
    mock_foreca_client.location_info = AsyncMock(
        return_value=type("L", (), {"name": None})()
    )

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_LOCATION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], SECOND_LOCATION_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Foreca"


@pytest.mark.usefixtures("mock_setup_entry", "mock_foreca_client")
async def test_duplicate_api_key_aborts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the same API key cannot be set up twice."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
) -> None:
    """Test a new API key is checked against the first location and stored."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {CONF_API_KEY: "new-key"}
    mock_foreca_client.current.assert_awaited_once_with("24.94,60.17")


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (ForecaAuthError, "invalid_auth"),
        (ForecaConnectionError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_errors_then_recovers(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
    exception: type[Exception],
    error: str,
) -> None:
    """Test a rejected new key keeps the form open, then succeeds once fixed."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_foreca_client.location_info.side_effect = exception
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert mock_config_entry.data == {CONF_API_KEY: "test-key"}

    mock_foreca_client.location_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {CONF_API_KEY: "new-key"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_without_locations_uses_home(
    hass: HomeAssistant, mock_foreca_client: MagicMock
) -> None:
    """Test an entry whose locations were all removed checks the home location."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Foreca", data={CONF_API_KEY: "test-key"}
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    mock_foreca_client.current.assert_awaited_once_with(
        f"{hass.config.longitude},{hass.config.latitude}"
    )


@pytest.mark.parametrize(
    "api_key",
    [pytest.param("new-key", id="new_key"), pytest.param("test-key", id="same_key")],
)
async def test_reauth_on_loaded_entry(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
    api_key: str,
) -> None:
    """Test a key rejected at runtime is replaced and the entry reloaded."""
    await init_integration(hass, mock_config_entry)
    mock_foreca_client.current.side_effect = ForecaAuthError
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH

    mock_foreca_client.current.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_API_KEY: api_key}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {CONF_API_KEY: api_key}

    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID).state != STATE_UNAVAILABLE
    assert mock_foreca_client.forecast_daily.await_count == 2


@pytest.mark.parametrize(
    "api_key",
    [pytest.param("new-key", id="new_key"), pytest.param("test-key", id="same_key")],
)
async def test_reauth_after_failed_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_foreca_client: MagicMock,
    api_key: str,
) -> None:
    """Test an entry whose setup failed on the key is set up with the new one."""
    mock_foreca_client.current.side_effect = ForecaAuthError
    await init_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    [flow] = hass.config_entries.flow.async_progress()

    mock_foreca_client.current.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_API_KEY: api_key}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {CONF_API_KEY: api_key}

    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED


@pytest.mark.usefixtures("mock_setup_entry", "mock_foreca_client")
async def test_reauth_with_other_entrys_key_aborts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the new key cannot be one another entry already uses."""
    mock_config_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN, title="Foreca", data={CONF_API_KEY: "other-key"}
    ).add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "other-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data == {CONF_API_KEY: "test-key"}
