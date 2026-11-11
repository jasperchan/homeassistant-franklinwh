"""Push message parsing, diffing and attribute budgeting for FranklinWH.

Pure Python (no Home Assistant imports). ``items`` are the raw dicts of
``selectTerPushMessageListApp`` (``Client.get_messages``): id, title, type,
subType, content, notice, readStatus, creationTime (UTC), deviceSendTime and
displayTime (gateway-local), gatewayName, userMessageId, jumpScheme...
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, tzinfo
import json
import logging
from typing import Any, Final

from .alarms import parse_alarm_time
from .const import (
    ATTR_MAX_BYTES,
    ATTR_MESSAGES,
    MESSAGE_CONTENT_MAX,
    MESSAGE_TITLE_MAX,
)

_LOGGER = logging.getLogger(__name__)

type Message = dict[str, Any]

MESSAGE_KEYS: Final = ("id", "title", "type", "sub_type", "content", "received", "read")
EVENT_TYPES: Final[list[str]] = ["received"]


def truncate(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters, marking the cut with an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def parse_message(item: Mapping[str, Any], tz: tzinfo) -> Message:
    """Parse one raw message into the attribute dict shared by sensor and event.

    ``received`` is ``deviceSendTime`` (or ``displayTime``) read in the
    gateway zone ``tz``; ``creationTime`` (UTC) is the fallback. ``read`` is
    ``readStatus == 1``. Raises ``KeyError``/``ValueError``/``TypeError`` when
    ``id`` is unusable.
    """
    received = parse_alarm_time(
        item.get("deviceSendTime") or item.get("displayTime"), tz
    ) or parse_alarm_time(item.get("creationTime"), UTC)
    read_status = item.get("readStatus")
    return {
        "id": int(item["id"]),
        "title": truncate(str(item.get("title") or ""), MESSAGE_TITLE_MAX),
        "type": item.get("type"),
        "sub_type": item.get("subType"),
        "content": truncate(str(item.get("content") or ""), MESSAGE_CONTENT_MAX),
        "received": received.isoformat() if received else None,
        "read": None if read_status is None else read_status == 1,
    }


def parse_messages(
    items: Iterable[Mapping[str, Any]], tz: tzinfo, gateway_id: str | None = None
) -> list[Message]:
    """Parse a message list, newest first (by id), skipping malformed items.

    The list endpoint is account-level (every item carries its own
    ``gatewayId``); with ``gateway_id`` set, items that name another gateway
    are skipped so a multi-gateway account does not see the other systems'
    messages under this gateway. Items without a ``gatewayId`` are kept.
    """
    messages: dict[int, Message] = {}
    for item in items or ():
        if (
            gateway_id is not None
            and (item.get("gatewayId") or gateway_id) != gateway_id
        ):
            _LOGGER.debug(
                "Skipping message %s of gateway %s",
                item.get("id"),
                item.get("gatewayId"),
            )
            continue
        try:
            message = parse_message(item, tz)
        except (KeyError, ValueError, TypeError, AttributeError) as err:
            _LOGGER.debug("Skipping malformed message %s: %s", item, err)
            continue
        messages[message["id"]] = message
    return [messages[i] for i in sorted(messages, reverse=True)]


def new_messages(known: Iterable[int], messages: Sequence[Message]) -> list[Message]:
    """Return the messages whose id is not in ``known``, oldest first."""
    known_ids = set(known)
    return [m for m in reversed(messages) if m["id"] not in known_ids]


def attribute_bytes(attributes: Mapping[str, Any]) -> int:
    """Size of ``attributes`` as the recorder would serialise them."""
    return len(json.dumps(attributes, ensure_ascii=False, default=str).encode("utf-8"))


def latest_title(messages: Sequence[Message]) -> str | None:
    """State of the ``latest_message`` sensor: the newest title."""
    return messages[0]["title"] if messages else None


def latest_attributes(
    messages: Sequence[Message], budget: int = ATTR_MAX_BYTES
) -> dict[str, Any]:
    """Attributes of the ``latest_message`` sensor, kept under ``budget`` bytes.

    The newest message's fields sit at the top level; ``messages`` holds the
    whole list (newest first). Older entries are dropped from the list until
    the serialised attributes fit. No ``fetched_at``: the attributes change
    only when a message does, so the recorder writes nothing in between.
    """
    latest = messages[0] if messages else {}
    attributes: dict[str, Any] = {
        key: latest.get(key) for key in MESSAGE_KEYS if key != "title"
    }
    kept = list(messages)
    attributes[ATTR_MESSAGES] = kept
    while kept and attribute_bytes(attributes) > budget:
        kept.pop()
    return attributes


def diagnostics_messages(messages: Iterable[Message]) -> list[dict[str, Any]]:
    """Messages with their content dropped, for the diagnostics download."""
    return [{k: v for k, v in m.items() if k != "content"} for m in messages]
