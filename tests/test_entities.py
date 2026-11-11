"""Entity-level tests for the raw payload / message sensors and event entities.

Runs on the stubbed Home Assistant surface from conftest (or the real one in
an HA dev environment) with the fake client from test_coordinator.
"""

from datetime import datetime
import json
from typing import Any

from conftest import GATEWAY_ID, REPO_ROOT, T0, load_fixture, run
from franklin_wh import binary_sensor, event
from franklin_wh.const import ATTR_MAX_BYTES, EVENT_ALARM, EVENT_MESSAGE
from franklin_wh.sensor import (
    COMPOSITE_SENSORS,
    MESSAGE_LIST_SENSORS,
    RAW_SENSORS,
    SLOW_SENSORS,
    FranklinWHDataSensorEntity,
)
import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event

DATA_SENSORS = (*COMPOSITE_SENSORS, *SLOW_SENSORS, *MESSAGE_LIST_SENSORS, *RAW_SENSORS)


@pytest.fixture
def refreshed(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    return coordinator


def entity(coordinator, key: str) -> FranklinWHDataSensorEntity:
    description = next(d for d in DATA_SENSORS if d.key == key)
    return FranklinWHDataSensorEntity(coordinator, description, ConfigEntry())


def test_unique_keys_and_translations():
    keys = [d.key for d in DATA_SENSORS]
    assert len(keys) == len(set(keys))
    strings = json.loads((REPO_ROOT / "strings.json").read_text(encoding="utf-8"))
    icons = json.loads((REPO_ROOT / "icons.json").read_text(encoding="utf-8"))
    for description in DATA_SENSORS:
        assert description.translation_key == description.key
        assert description.key in strings["entity"]["sensor"], description.key
    for description in binary_sensor.BINARY_SENSORS:
        assert description.key in strings["entity"]["binary_sensor"]
    assert set(strings["entity"]["event"]) == {"alarm", "message"}
    for key in (d.key for d in RAW_SENSORS):
        assert icons["entity"]["sensor"][key]["default"] == "mdi:code-json"
    assert "message" in icons["entity"]["event"]
    assert all(d.fetched_at for d in RAW_SENSORS)
    # the message list refreshes every 5 min with nothing new; a fetched_at
    # would make the recorder store the whole list again each time
    assert not any(d.fetched_at for d in MESSAGE_LIST_SENSORS)
    assert all(
        d.entity_category is not None for d in (*RAW_SENSORS, *MESSAGE_LIST_SENSORS)
    )


@pytest.mark.parametrize("key", [d.key for d in (*MESSAGE_LIST_SENSORS, *RAW_SENSORS)])
def test_raw_entity_attributes_fit_and_serialise(refreshed, key):
    e = entity(refreshed, key)
    assert e.unique_id == f"{GATEWAY_ID}_{key}"
    assert e.available
    attrs = e.extra_state_attributes
    if key in {d.key for d in RAW_SENSORS}:
        assert attrs["fetched_at"] == T0.isoformat()
    else:
        assert "fetched_at" not in attrs
    encoded = json.dumps(attrs, ensure_ascii=False)  # no default needed
    assert len(encoded.encode()) < ATTR_MAX_BYTES, key
    assert "dropped" not in attrs


def test_raw_entity_states(refreshed):
    expected: dict[str, Any] = {
        "raw_runtime": "Self-Consumption",
        "raw_composite_misc": "online",
        "raw_alarms": 1,
        "raw_apowers": 1,
        "raw_system_setting": T0,
        "raw_warranty": "2038-11-09",
        "raw_gateway": "V10R11B60D00_SYS_aP1X_20_2S_AHUB",
        "raw_export_settings": "solar_and_apower",
        "raw_tou": "Self-Consumption",
        "latest_message": "4G signal is poor",
    }
    for key, value in expected.items():
        assert entity(refreshed, key).native_value == value, key
    assert isinstance(entity(refreshed, "raw_system_setting").native_value, datetime)


def test_raw_entity_attributes_are_verbatim(refreshed):
    composite = load_fixture("composite.json")
    attrs = entity(refreshed, "raw_runtime").extra_state_attributes
    del attrs["fetched_at"]
    assert attrs == composite["runtimeData"]
    attrs = entity(refreshed, "raw_alarms").extra_state_attributes
    assert attrs["currentAlarmVOList"] == composite["currentAlarmVOList"]
    attrs = entity(refreshed, "raw_apowers").extra_state_attributes
    assert attrs["result"] == load_fixture("apowers.json")
    attrs = entity(refreshed, "raw_gateway").extra_state_attributes
    assert attrs["zoneInfo"] == "America/Los_Angeles"
    attrs = entity(refreshed, "raw_export_settings").extra_state_attributes
    assert attrs == {
        "mode": "SOLAR_AND_APOWER",
        "limit_kw": None,
        "fetched_at": T0.isoformat(),
    }
    attrs = entity(refreshed, "latest_message").extra_state_attributes
    assert attrs["id"] == 6569334
    assert [m["id"] for m in attrs["messages"]] == [6569334, 6565687, 6565683]


def test_entities_unavailable_without_data(coordinator, client):
    coordinator.client = client  # HA builds entities only after a first refresh
    for key in ("raw_runtime", "raw_tou", "latest_message"):
        e = entity(coordinator, key)
        assert not e.available
        assert e.native_value is None
        assert e.extra_state_attributes is None


def test_phase_one_sensors_have_no_fetched_at(refreshed):
    attrs = entity(refreshed, "active_alarms").extra_state_attributes
    assert "fetched_at" not in attrs
    assert entity(refreshed, "ambient_temperature").extra_state_attributes is None


def test_message_event_entity(refreshed):
    e = event.FranklinWHMessageEventEntity(refreshed, ConfigEntry())
    assert e.unique_id == f"{GATEWAY_ID}_message"
    assert e.event_types == ["received"]
    assert e.available
    message = {
        "id": 7,
        "title": "t",
        "type": 1,
        "sub_type": 2,
        "content": "c",
        "received": "2026-11-11T13:30:00-08:00",
        "read": False,
    }
    e._on_bus_event(Event(EVENT_MESSAGE, {"gateway_id": "other", **message}))
    assert not hasattr(e, "last_event_type")
    e._on_bus_event(Event(EVENT_MESSAGE, {"gateway_id": GATEWAY_ID, **message}))
    assert e.last_event_type == "received"
    assert e.last_event_attributes == message


def test_alarm_event_entity(refreshed):
    e = event.FranklinWHAlarmEventEntity(refreshed, ConfigEntry())
    assert e.unique_id == f"{GATEWAY_ID}_alarm"
    assert e.event_types == ["raised", "cleared"]
    payload = {
        "gateway_id": GATEWAY_ID,
        "action": "cleared",
        "id": 1,
        "code": "5144",
        "time": "2026-11-10T15:01:30-08:00",
    }
    e._on_bus_event(Event(EVENT_ALARM, payload))
    assert e.last_event_type == "cleared"
    assert e.last_event_attributes == {
        "id": 1,
        "code": "5144",
        "since": "2026-11-10T15:01:30-08:00",
    }


def test_sensor_tables_are_appended_in_setup():
    source = (REPO_ROOT / "sensor.py").read_text(encoding="utf-8")
    assert source.index(
        "MESSAGE_LIST_SENSORS, FranklinWHDataSensorEntity"
    ) > source.index("SLOW_SENSORS, FranklinWHDataSensorEntity")
    assert "RAW_SENSORS, FranklinWHDataSensorEntity" in source
