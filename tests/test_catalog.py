"""Tests for the alarm code catalog and its generator."""

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path

from conftest import REPO_ROOT
from franklin_wh import alarm_codes
from franklin_wh.alarm_codes import ALARM_CODES, alarm_name
from franklin_wh.alarms import parse_alarm
import pytest

AT = datetime(2026, 11, 11, 21, 0, tzinfo=UTC)


def _generator():
    path = REPO_ROOT / "tools" / "gen_alarm_codes.py"
    spec = importlib.util.spec_from_file_location("gen_alarm_codes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_lookup():
    assert len(ALARM_CODES) == 477
    assert alarm_name("5144") == "NO.1 MPPT The arc lock fault occurs"
    assert alarm_name("1001") == "Relay Normally Close Failure of Grid"
    assert alarm_name(" 100a ") == alarm_name("100A")
    assert alarm_name("0000") is None
    assert alarm_name(None) is None
    assert alarm_name(5144) == alarm_name("5144")


def test_parse_alarm_uses_catalog_when_cloud_has_no_name(tz):
    item = {"id": 1, "alarmCode": "5144", "time": "2026-11-10 15:01:30"}
    assert parse_alarm(item, tz, AT).name == "NO.1 MPPT The arc lock fault occurs"
    # the cloud's own name wins over the catalog
    named = {**item, "logNameEn": "cloud name"}
    assert parse_alarm(named, tz, AT).name == "cloud name"
    unknown = {**item, "alarmCode": "FFFF"}
    assert parse_alarm(unknown, tz, AT).name == ""


def test_module_matches_generator_output():
    gen = _generator()
    source = Path(alarm_codes.__file__).read_text(encoding="utf-8")
    assert source == gen.render(
        gen.catalog([{"alarmCode": c, "enLogName": n} for c, n in ALARM_CODES.items()])
    ), "alarm_codes.py was edited by hand; regenerate it with tools/gen_alarm_codes.py"


@pytest.mark.parametrize(
    "shape",
    ["list", "envelope", "probe"],
)
def test_generator_accepts_every_capture_shape(tmp_path, shape):
    gen = _generator()
    entries = [
        {"alarmCode": "1002", "logName": "x", "enLogName": "Second"},
        {"alarmCode": " 100a", "logName": "y", "enLogName": " First "},
        {"alarmCode": "1003", "enLogName": ""},  # no name: skipped
    ]
    payload = {
        "list": entries,
        "envelope": {"code": 200, "result": entries},
        "probe": {"runlog_catalog": {"code": 200, "result": entries}},
    }[shape]
    source = tmp_path / "in.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "alarm_codes.py"
    assert gen.main([str(source), "-o", str(output)]) == 0

    spec = importlib.util.spec_from_file_location("generated", output)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ALARM_CODES == {"1002": "Second", "100A": "First"}
    assert module.alarm_name("100a") == "First"


def test_generator_rejects_conflicts_and_bad_shapes():
    gen = _generator()
    with pytest.raises(ValueError):
        gen.catalog(
            [
                {"alarmCode": "1", "enLogName": "a"},
                {"alarmCode": "1", "enLogName": "b"},
            ]
        )
    with pytest.raises(TypeError):
        gen.extract_entries({"nothing": 1})
    with pytest.raises(TypeError):
        gen.extract_entries("text")
