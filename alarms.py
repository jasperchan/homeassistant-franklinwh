"""Alarm parsing, diffing and enum tables for FranklinWH.

Pure Python: nothing in here imports Home Assistant, so the alarm transition
logic can be unit tested without an HA install.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, tzinfo
import logging
from typing import Any, Final, Literal

from .alarm_codes import alarm_name

_LOGGER = logging.getLogger(__name__)

# Items skipped by parse_alarms that were already reported at WARNING; later
# occurrences (the composite is polled every minute) are logged at DEBUG.
_REPORTED_MALFORMED: set[str] = set()
_REPORTED_MALFORMED_MAX: Final = 100

type AlarmAction = Literal["raised", "cleared"]


@dataclass(frozen=True)
class AlarmInfo:
    """One active alarm from ``currentAlarmVOList``."""

    id: int  # currentAlarmVOList[].id
    code: str  # alarmCode, e.g. "5144"
    common_code: str  # commonAlarmCode, e.g. "5#44"
    name: str  # logNameEn
    common_name: str  # commonLogNameEn
    level: int  # vendor scale, passed through
    since: datetime  # ``time`` parsed in the gateway zone (see parse_alarm)
    equipment_sn: str  # alarmEqSn
    explanation: str  # alarmExplanationEn
    plan: str  # vendor fix steps, newline separated


@dataclass(frozen=True)
class AlarmTransition:
    """An alarm appearing in or disappearing from the active list."""

    action: AlarmAction
    alarm: AlarmInfo
    at: datetime  # detection time (UTC)


def parse_alarm_time(raw: Any, tz: tzinfo) -> datetime | None:
    """Parse an alarm ``time`` ("YYYY-MM-DD HH:MM:SS" or ISO 8601) in ``tz``.

    Returns ``None`` when the value is missing or not a parseable string; an
    offset inside the string wins over ``tz``.
    """
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=tz)


def parse_alarm(item: Mapping[str, Any], tz: tzinfo, fallback: datetime) -> AlarmInfo:
    """Parse one ``currentAlarmVOList`` item.

    ``since`` is ``time`` parsed in ``tz``; when ``time`` is missing or
    unparseable (the sibling ``createTime`` is already null in captures) the
    alarm is kept and ``fallback`` is used so it still counts as active.
    ``name`` falls back to the alarm code catalog when the cloud item carries
    no ``logNameEn``/``logName``.
    Raises ``KeyError``/``ValueError``/``TypeError`` when ``id`` is unusable.
    """
    since = parse_alarm_time(item.get("time"), tz)
    if since is None:
        _LOGGER.debug(
            "Alarm %s has no usable time (%r); using %s",
            item.get("id"),
            item.get("time"),
            fallback,
        )
        since = fallback
    code = str(item.get("alarmCode") or "")
    return AlarmInfo(
        id=int(item["id"]),
        code=code,
        common_code=str(item.get("commonAlarmCode") or ""),
        name=str(
            item.get("logNameEn") or item.get("logName") or alarm_name(code) or ""
        ),
        common_name=str(item.get("commonLogNameEn") or ""),
        level=int(item.get("level") or 0),
        since=since,
        equipment_sn=str(item.get("alarmEqSn") or ""),
        explanation=str(item.get("alarmExplanationEn") or ""),
        plan=str(item.get("plan") or ""),
    )


def parse_alarms(
    composite: Mapping[str, Any],
    tz: tzinfo,
    at: datetime,
    known: Mapping[int, AlarmInfo] | None = None,
) -> dict[int, AlarmInfo]:
    """Parse ``composite["currentAlarmVOList"]`` keyed by alarm id.

    ``at`` (detection time) stands in for a missing ``time``; an alarm already
    in ``known`` keeps its earlier ``since`` so the value does not drift from
    poll to poll. Items without a usable ``id`` are skipped (warning once,
    then debug) so a single odd alarm cannot take down the whole poll.
    """
    alarms: dict[int, AlarmInfo] = {}
    for item in composite.get("currentAlarmVOList") or ():
        try:
            alarm = parse_alarm(item, tz, at)
            if (
                known
                and (earlier := known.get(alarm.id)) is not None
                and alarm.since == at
            ):
                alarm = replace(alarm, since=earlier.since)
        except (KeyError, ValueError, TypeError, AttributeError) as err:
            _report_malformed(item, err)
            continue
        alarms[alarm.id] = alarm
    return alarms


def _report_malformed(item: Any, err: Exception) -> None:
    """Warn once per distinct malformed item, then log at debug."""
    key = repr(item)
    if key in _REPORTED_MALFORMED:
        log = _LOGGER.debug
    else:
        if len(_REPORTED_MALFORMED) >= _REPORTED_MALFORMED_MAX:
            _REPORTED_MALFORMED.clear()
        _REPORTED_MALFORMED.add(key)
        log = _LOGGER.warning
    log("Skipping malformed alarm %s: %s", item, err)


def sort_alarms(alarms: Mapping[int, AlarmInfo]) -> tuple[AlarmInfo, ...]:
    """Return the alarms ordered by ``since`` (then id for a stable order)."""
    return tuple(sorted(alarms.values(), key=lambda a: (a.since, a.id)))


def diff_alarms(
    known: Mapping[int, AlarmInfo],
    current: Mapping[int, AlarmInfo],
    at: datetime,
) -> list[AlarmTransition]:
    """Return the transitions from ``known`` to ``current``.

    Raised alarms (ids only in ``current``) come first, then cleared alarms
    (ids only in ``known``); each group is ordered by ``since``.
    """
    raised = sort_alarms({i: a for i, a in current.items() if i not in known})
    cleared = sort_alarms({i: a for i, a in known.items() if i not in current})
    return [AlarmTransition("raised", a, at) for a in raised] + [
        AlarmTransition("cleared", a, at) for a in cleared
    ]


def alarm_attributes(alarm: AlarmInfo) -> dict[str, Any]:
    """Attribute dict shared by the sensor, the event entity and the bus payload."""
    return {
        "id": alarm.id,
        "code": alarm.code,
        "common_code": alarm.common_code,
        "name": alarm.name,
        "level": alarm.level,
        "since": alarm.since.isoformat(),
        "equipment_sn": alarm.equipment_sn,
        "explanation": alarm.explanation,
        "plan": alarm.plan,
    }


# Enum tables. Keys are the raw vendor codes, values are the translation
# option keys used in strings.json.

# pe_stat[i] (power electronics / PCS state)
PCS_STATE: Final[dict[int, str]] = {
    0: "off",
    1: "standby",
    2: "initialization",
    3: "fault",
    4: "warning",
    5: "running",
    6: "charging",
    7: "discharging",
    8: "online",
    9: "off_grid",
}

# bms_work[i]; firmware encodes it as run_status + 5
BMS_STATE: Final[dict[int, str]] = {
    0: "off",
    1: "initialization",
    2: "fault",
    3: "warning",
    4: "shutdown",
    5: "standby",
    6: "charging",
    7: "discharging",
}

# deviceStatus. Observed: 1 while the aPower was in standby (this system,
# 2026-11-11) and while another system was discharging (franklinwh-cloud live
# trace), so 1 is "online", not "charging" as one third-party glossary claims.
# 0 is assumed to be offline; other values are unmapped until observed.
DEVICE_STATUS: Final[dict[int, str]] = {
    0: "offline",
    1: "online",
}

# connType (also cmdType 339 currentNetType)
CONN_TYPE: Final[dict[int, str]] = {
    2: "ethernet",
    3: "wifi",
    4: "cellular",
}

# franklinwh.ExportMode member names
EXPORT_MODE: Final[dict[str, str]] = {
    "NO_EXPORT": "no_export",
    "SOLAR_ONLY": "solar_only",
    "SOLAR_AND_APOWER": "solar_and_apower",
}

EVENT_TYPES: Final[list[str]] = ["raised", "cleared"]


def enum_options(table: Mapping[Any, str]) -> list[str]:
    """Return the distinct option keys of a table in table order."""
    return list(dict.fromkeys(table.values()))


def enum_option(table: Mapping[Any, str], raw: Any) -> str | None:
    """Map a raw vendor code to its option key, ``None`` when unknown."""
    if raw is None:
        return None
    option = table.get(raw)
    if option is None:
        _LOGGER.debug("Unknown code %r (known: %s)", raw, sorted(table))
    return option
