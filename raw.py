"""Raw payload helpers for the ``raw_*`` diagnostic sensors.

Pure Python. Every function returns JSON-serialisable data (enums and
datetimes become strings) so the dicts can be stored as entity attributes
verbatim, with no renaming, and the recorder keeps them as history.
"""

from collections.abc import Mapping, Sequence
import dataclasses
from datetime import date, datetime
from enum import Enum
import json
import logging
from typing import Any

from . import composite as values
from .const import ATTR_MAX_BYTES

_LOGGER = logging.getLogger(__name__)

type Composite = Mapping[str, Any]

_warned_drops: set[tuple[str, ...]] = set()  # fit() warns once per dropped set

RAW_LIST_KEY = "result"  # list-valued endpoints are stored under the envelope key
COMPOSITE_MISC_EXCLUDED = frozenset({"runtimeData", "currentAlarmVOList"})


def jsonable(value: Any) -> Any:
    """Recursively convert ``value`` into JSON-serialisable types."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    return str(value)


def attribute_bytes(attributes: Mapping[str, Any]) -> int:
    """Size of ``attributes`` as the recorder would serialise them."""
    return len(json.dumps(attributes, ensure_ascii=False, default=str).encode("utf-8"))


def fit(attributes: dict[str, Any], budget: int = ATTR_MAX_BYTES) -> dict[str, Any]:
    """Keep ``attributes`` under ``budget`` bytes.

    No captured payload comes anywhere near the limit (the largest, the
    runtime data, is about 1.5 KB), so this only guards against a future
    firmware adding a huge member: the largest top-level members are replaced
    by a marker string until the dict fits, and ``dropped`` lists their keys.
    The entities re-run this on every poll and attribute read, so each
    distinct set of dropped keys is logged at WARNING once, then at DEBUG.
    """
    if attribute_bytes(attributes) <= budget:
        return attributes
    fitted = dict(attributes)
    dropped: list[str] = []
    by_size = sorted(
        fitted, key=lambda k: attribute_bytes({k: fitted[k]}), reverse=True
    )
    for key in by_size:
        size = attribute_bytes({key: fitted[key]})
        fitted[key] = f"<dropped {size} bytes>"
        dropped.append(key)
        fitted["dropped"] = dropped
        if attribute_bytes(fitted) <= budget:
            break
    key = tuple(dropped)
    log = _LOGGER.debug if key in _warned_drops else _LOGGER.warning
    _warned_drops.add(key)
    log("Raw attributes over %d bytes; dropped %s", budget, dropped)
    return fitted


# composite (per poll)


def runtime(composite: Composite) -> dict[str, Any]:
    """``runtimeData`` verbatim."""
    return fit(jsonable(composite["runtimeData"]))


def runtime_state(composite: Composite) -> str | None:
    """Current mode name (``runtimeData.name``)."""
    return composite["runtimeData"].get("name")


def composite_misc(composite: Composite) -> dict[str, Any]:
    """The composite minus ``runtimeData`` and ``currentAlarmVOList``."""
    return fit(
        jsonable(
            {k: v for k, v in composite.items() if k not in COMPOSITE_MISC_EXCLUDED}
        )
    )


def composite_misc_state(composite: Composite) -> str | None:
    """Decoded ``deviceStatus``."""
    return values.device_status(composite)


def alarms(composite: Composite) -> dict[str, Any]:
    """``currentAlarmVOList`` verbatim under its own key."""
    return fit(
        {"currentAlarmVOList": jsonable(composite.get("currentAlarmVOList") or [])}
    )


def alarms_count(composite: Composite) -> int:
    """Number of items in ``currentAlarmVOList``."""
    return len(composite.get("currentAlarmVOList") or [])


# slow group (hourly)


def result_list(items: Sequence[Any]) -> dict[str, Any]:
    """A list-valued endpoint result under the API envelope key ``result``."""
    return fit({RAW_LIST_KEY: jsonable(list(items))})


def count(items: Sequence[Any]) -> int:
    """Number of items in a list-valued result."""
    return len(items)


def mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A dict-valued endpoint result verbatim."""
    return fit(jsonable(payload))


def warranty_state(warranty: Mapping[str, Any]) -> str | None:
    """System warranty expiration (``expirationTime``)."""
    return warranty.get("expirationTime")


def gateway_state(gateway: Mapping[str, Any]) -> str | None:
    """Gateway firmware ``version``."""
    return gateway.get("version")


def export_settings(export: Any) -> dict[str, Any]:
    """``franklinwh.ExportSettings`` as a dict (``mode`` is the member name)."""
    return {"mode": jsonable(export.mode), "limit_kw": export.limit_kw}


def tou_state(tou: Mapping[str, Any]) -> str | None:
    """Name of the TOU list entry that is current (``currendId``)."""
    current = tou.get("currendId")
    for entry in tou.get("list") or ():
        if entry.get("id") == current:
            return entry.get("name")
    return None
