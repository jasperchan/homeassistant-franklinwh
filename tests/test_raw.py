"""Tests for the raw payload helpers against the captures."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
import json

from franklin_wh import raw
from franklin_wh.const import ATTR_MAX_BYTES
from franklinwh import ExportMode, ExportSettings
import pytest


class Colour(Enum):
    RED = 1


@dataclass(frozen=True)
class Point:
    x: int
    when: datetime


def test_jsonable():
    value = {
        "enum": Colour.RED,
        "dt": datetime(2026, 11, 11, 21, 0, tzinfo=UTC),
        "date": date(2026, 11, 11),
        "tuple": (1, "a", None),
        "set": {1},
        "nested": {"dc": Point(1, datetime(2026, 1, 1, tzinfo=UTC))},
        "obj": object(),
        1: True,
        "f": 1.5,
    }
    out = raw.jsonable(value)
    assert out["enum"] == "RED"
    assert out["dt"] == "2026-11-11T21:00:00+00:00"
    assert out["date"] == "2026-11-11"
    assert out["tuple"] == [1, "a", None]
    assert out["set"] == [1]
    assert out["nested"] == {"dc": {"x": 1, "when": "2026-01-01T00:00:00+00:00"}}
    assert out["obj"].startswith("<object object")
    assert out["1"] is True
    assert out["f"] == 1.5
    json.dumps(out)


def test_runtime(composite):
    attrs = raw.runtime(composite)
    assert attrs == composite["runtimeData"], "verbatim, no renaming"
    assert attrs is not composite["runtimeData"]
    assert raw.runtime_state(composite) == "Self-Consumption"


def test_composite_misc(composite):
    attrs = raw.composite_misc(composite)
    assert set(attrs) == {
        "currentWorkMode",
        "deviceStatus",
        "solarHaveVo",
        "valid",
        "csipAuxGatewayOnline",
    }
    assert attrs["solarHaveVo"] == composite["solarHaveVo"]
    assert raw.composite_misc_state(composite) == "charging"


def test_alarms(composite):
    attrs = raw.alarms(composite)
    assert list(attrs) == ["currentAlarmVOList"]
    assert attrs["currentAlarmVOList"] == composite["currentAlarmVOList"]
    assert attrs["currentAlarmVOList"][0]["alarmCode"] == "5144"
    assert raw.alarms_count(composite) == 1
    assert raw.alarms({})["currentAlarmVOList"] == []
    assert raw.alarms_count({"currentAlarmVOList": None}) == 0


def test_slow_group_payloads(apowers, system_setting, warranty, gateway_list, tou):
    assert raw.result_list(apowers) == {"result": apowers}
    assert raw.count(apowers) == 1
    assert raw.mapping(system_setting) == system_setting
    assert raw.mapping(warranty) == warranty
    assert raw.warranty_state(warranty) == "2038-11-09"
    assert raw.gateway_state(gateway_list[0]) == "V10R11B60D00_SYS_aP1X_20_2S_AHUB"
    assert raw.tou_state(tou) == "Self-Consumption"
    assert raw.tou_state({"currendId": 1, "list": []}) is None
    export = ExportSettings(mode=ExportMode.SOLAR_AND_APOWER, limit_kw=None)
    assert raw.export_settings(export) == {"mode": "SOLAR_AND_APOWER", "limit_kw": None}
    export = ExportSettings(mode=ExportMode.SOLAR_ONLY, limit_kw=5.0)
    assert raw.export_settings(export) == {"mode": "SOLAR_ONLY", "limit_kw": 5.0}


@pytest.mark.parametrize(
    ("fn", "fixture"),
    [
        (raw.runtime, "composite"),
        (raw.composite_misc, "composite"),
        (raw.alarms, "composite"),
        (raw.result_list, "apowers"),
        (raw.mapping, "system_setting"),
        (raw.mapping, "warranty"),
        (raw.mapping, "tou"),
    ],
)
def test_raw_attributes_fit_and_serialise(fn, fixture, request):
    attrs = fn(request.getfixturevalue(fixture))
    encoded = json.dumps(attrs, ensure_ascii=False)  # no default: already plain
    assert len(encoded.encode()) < ATTR_MAX_BYTES
    assert "dropped" not in attrs


def test_raw_gateway_fits(gateway_list):
    attrs = raw.mapping(gateway_list[0])
    assert len(json.dumps(attrs).encode()) < ATTR_MAX_BYTES


def test_fit_drops_largest_members(caplog):
    attrs = {"small": 1, "big": "x" * 20000, "medium": "y" * 3000}
    raw._warned_drops.clear()
    with caplog.at_level("WARNING", logger="franklin_wh.raw"):
        fitted = raw.fit(dict(attrs))
    assert raw.attribute_bytes(fitted) <= ATTR_MAX_BYTES
    assert fitted["small"] == 1
    assert fitted["medium"] == "y" * 3000
    assert fitted["big"].startswith("<dropped ")
    assert fitted["dropped"] == ["big"]
    assert "dropped ['big']" in caplog.text
    # the same drop again (every poll and attribute read) is not a new warning
    caplog.clear()
    with caplog.at_level("DEBUG", logger="franklin_wh.raw"):
        raw.fit(dict(attrs))
    assert [r.levelname for r in caplog.records] == ["DEBUG"]
    # a different set of dropped keys warns again
    caplog.clear()
    with caplog.at_level("WARNING", logger="franklin_wh.raw"):
        raw.fit({"other": "z" * 20000})
    assert "dropped ['other']" in caplog.text
    # small payloads pass through untouched
    small = {"a": 1}
    assert raw.fit(small) is small
