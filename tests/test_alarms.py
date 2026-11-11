"""Tests for alarm parsing, diffing and enum tables."""

from collections import deque
import copy
from datetime import UTC, datetime, timedelta

from franklin_wh.alarms import (
    BMS_STATE,
    CONN_TYPE,
    DEVICE_STATUS,
    EXPORT_MODE,
    PCS_STATE,
    AlarmInfo,
    AlarmTransition,
    alarm_attributes,
    diff_alarms,
    enum_option,
    enum_options,
    parse_alarms,
    sort_alarms,
)

AT = datetime(2026, 11, 11, 21, 0, tzinfo=UTC)


def _alarm(
    alarm_id: int, code: str = "5144", since: str = "2026-11-10 15:01:30"
) -> dict:
    return {
        "id": alarm_id,
        "gatewayId": "10060010A01X00000001",
        "alarmEqSn": "10050019A00X00000001",
        "alarmCode": code,
        "commonAlarmCode": "5#44",
        "level": 2,
        "time": since,
        "logNameEn": f"alarm {code}",
        "commonLogNameEn": "common",
        "alarmExplanationEn": "why",
        "plan": "1、a\n2、b",
    }


def test_parse_alarms(composite, tz):
    alarms = parse_alarms(composite, tz, AT)
    assert list(alarms) == [2756389132]
    alarm = alarms[2756389132]
    assert alarm.id == 2756389132
    assert alarm.code == "5144"
    assert alarm.common_code == "5#44"
    assert alarm.name == "NO.1 MPPT The arc lock fault occurs"
    assert alarm.common_name == "The arc lock fault occurs"
    assert alarm.level == 2
    assert alarm.since.isoformat() == "2026-11-10T15:01:30-08:00"
    assert alarm.since.utcoffset() == timedelta(hours=-8)
    assert alarm.equipment_sn == "10050019A00X00000001"
    assert alarm.explanation.startswith("The arcing fault of the PV branch")
    assert alarm.plan.count("\n") == 2
    assert alarm.plan.startswith("1、Check all connection points")


def test_parse_alarms_skips_malformed(composite, tz):
    composite = copy.deepcopy(composite)
    composite["currentAlarmVOList"].append({"id": "not-an-int", "time": "bad"})
    composite["currentAlarmVOList"].append({"alarmCode": "1"})  # no id/time
    assert list(parse_alarms(composite, tz, AT)) == [2756389132]


def test_parse_alarms_tolerates_missing_time(tz, caplog):
    # a null/absent/odd ``time`` must not drop an active alarm
    items = [
        {**_alarm(1), "time": None},
        {k: v for k, v in _alarm(2).items() if k != "time"},
        {**_alarm(3), "time": "not a date"},
        {**_alarm(4), "time": "2026-11-10T15:01:30"},  # ISO "T" separator
        {**_alarm(5), "time": "2026-11-10T15:01:30+00:00"},  # explicit offset
    ]
    with caplog.at_level("WARNING"):
        alarms = parse_alarms({"currentAlarmVOList": items}, tz, AT)
    assert sorted(alarms) == [1, 2, 3, 4, 5]
    assert alarms[1].since == AT
    assert alarms[2].since == AT
    assert alarms[3].since == AT
    assert alarms[4].since.isoformat() == "2026-11-10T15:01:30-08:00"
    assert alarms[5].since.isoformat() == "2026-11-10T15:01:30+00:00"
    assert "malformed" not in caplog.text


def test_parse_alarms_keeps_known_since_when_time_missing(tz):
    first = datetime(2026, 11, 11, 20, 0, tzinfo=UTC)
    known = parse_alarms(
        {"currentAlarmVOList": [{**_alarm(1), "time": None}]}, tz, first
    )
    assert known[1].since == first
    later = parse_alarms(
        {"currentAlarmVOList": [{**_alarm(1), "time": None}]}, tz, AT, known
    )
    assert later[1].since == first, "since must not drift poll to poll"
    # a real time wins over the remembered fallback
    fixed = parse_alarms({"currentAlarmVOList": [_alarm(1)]}, tz, AT, known)
    assert fixed[1].since.isoformat() == "2026-11-10T15:01:30-08:00"


def test_parse_alarms_warns_once_per_malformed_item(tz, caplog):
    bad = {"alarmCode": "9", "time": "2026-11-11 10:00:00"}  # no id
    with caplog.at_level("DEBUG", logger="franklin_wh.alarms"):
        parse_alarms({"currentAlarmVOList": [bad]}, tz, AT)
        parse_alarms({"currentAlarmVOList": [bad]}, tz, AT)
    records = [r for r in caplog.records if "malformed" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING", "DEBUG"]


def test_parse_alarms_empty_and_missing(tz):
    assert parse_alarms({"currentAlarmVOList": []}, tz, AT) == {}
    assert parse_alarms({"currentAlarmVOList": None}, tz, AT) == {}
    assert parse_alarms({}, tz, AT) == {}


def test_alarm_attributes(composite, tz):
    alarm = next(iter(parse_alarms(composite, tz, AT).values()))
    attrs = alarm_attributes(alarm)
    assert list(attrs) == [
        "id",
        "code",
        "common_code",
        "name",
        "level",
        "since",
        "equipment_sn",
        "explanation",
        "plan",
    ]
    assert attrs["since"] == "2026-11-10T15:01:30-08:00"
    assert attrs["id"] == 2756389132


def test_diff_no_change(composite, tz):
    known = parse_alarms(composite, tz, AT)
    assert diff_alarms(known, parse_alarms(composite, tz, AT), AT) == []


def test_diff_seed_is_callers_job(composite, tz):
    # diff against an empty known set reports everything as raised: the
    # coordinator must not call diff on the first poll (silent seeding)
    current = parse_alarms(composite, tz, AT)
    transitions = diff_alarms({}, current, AT)
    assert [t.action for t in transitions] == ["raised"]


def test_diff_cleared(composite, tz):
    known = parse_alarms(composite, tz, AT)
    transitions = diff_alarms(known, {}, AT)
    assert len(transitions) == 1
    assert transitions[0].action == "cleared"
    assert transitions[0].alarm.id == 2756389132
    assert transitions[0].at == AT


def test_diff_raised_new_id(tz):
    known = parse_alarms({"currentAlarmVOList": [_alarm(1)]}, tz, AT)
    current = parse_alarms(
        {"currentAlarmVOList": [_alarm(1), _alarm(2, "1001")]}, tz, AT
    )
    transitions = diff_alarms(known, current, AT)
    assert [(t.action, t.alarm.id) for t in transitions] == [("raised", 2)]


def test_diff_reoccurrence_same_code_new_id(tz):
    known = parse_alarms({"currentAlarmVOList": [_alarm(1)]}, tz, AT)
    current = parse_alarms(
        {"currentAlarmVOList": [_alarm(2, since="2026-11-11 08:00:00")]}, tz, AT
    )
    transitions = diff_alarms(known, current, AT)
    assert [(t.action, t.alarm.id) for t in transitions] == [
        ("raised", 2),
        ("cleared", 1),
    ]


def test_diff_ordering_by_since(tz):
    known = parse_alarms(
        {
            "currentAlarmVOList": [
                _alarm(10, since="2026-11-09 10:00:00"),
                _alarm(11, since="2026-11-08 10:00:00"),
            ]
        },
        tz,
        AT,
    )
    current = parse_alarms(
        {
            "currentAlarmVOList": [
                _alarm(21, since="2026-11-11 12:00:00"),
                _alarm(20, since="2026-11-11 11:00:00"),
            ]
        },
        tz,
        AT,
    )
    transitions = diff_alarms(known, current, AT)
    assert [(t.action, t.alarm.id) for t in transitions] == [
        ("raised", 20),
        ("raised", 21),
        ("cleared", 11),
        ("cleared", 10),
    ]


def test_sort_alarms(tz):
    alarms = parse_alarms(
        {
            "currentAlarmVOList": [
                _alarm(2, since="2026-11-11 12:00:00"),
                _alarm(1, since="2026-11-11 11:00:00"),
            ]
        },
        tz,
        AT,
    )
    assert [a.id for a in sort_alarms(alarms)] == [1, 2]


def test_history_maxlen(tz):
    history: deque[AlarmTransition] = deque(maxlen=50)
    alarm = next(
        iter(parse_alarms({"currentAlarmVOList": [_alarm(1)]}, tz, AT).values())
    )
    for i in range(60):
        history.append(AlarmTransition("raised", alarm, AT + timedelta(seconds=i)))
    assert len(history) == 50
    assert history[0].at == AT + timedelta(seconds=10)


def test_alarm_info_frozen(tz):
    alarm = next(
        iter(parse_alarms({"currentAlarmVOList": [_alarm(1)]}, tz, AT).values())
    )
    assert isinstance(alarm, AlarmInfo)
    try:
        alarm.code = "x"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("AlarmInfo must be frozen")


def test_enum_tables():
    assert enum_option(PCS_STATE, 8) == "online"
    assert enum_option(BMS_STATE, 5) == "standby"
    assert enum_option(DEVICE_STATUS, 1) == "charging"
    assert enum_option(CONN_TYPE, 3) == "wifi"
    assert enum_option(EXPORT_MODE, "SOLAR_AND_APOWER") == "solar_and_apower"
    assert enum_option(PCS_STATE, 42) is None
    assert enum_option(CONN_TYPE, None) is None
    assert enum_options(CONN_TYPE) == ["ethernet", "wifi", "cellular"]
    assert len(enum_options(PCS_STATE)) == 10
    assert len(enum_options(BMS_STATE)) == 8
