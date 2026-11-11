"""Tests for push message parsing, diffing and the attribute budget."""

import copy
import json

from franklin_wh.const import (
    ATTR_MAX_BYTES,
    MESSAGE_CONTENT_MAX,
    MESSAGE_LIST_SIZE,
    MESSAGE_TITLE_MAX,
)
from franklin_wh.messages import (
    MESSAGE_KEYS,
    attribute_bytes,
    diagnostics_messages,
    latest_attributes,
    latest_title,
    new_messages,
    parse_message,
    parse_messages,
    truncate,
)


def test_parse_message(messages, tz):
    message = parse_message(messages[0], tz)
    assert list(message) == list(MESSAGE_KEYS)
    assert message == {
        "id": 6569334,
        "title": "4G signal is poor",
        "type": 1,
        "sub_type": 1,
        "content": (
            "4G Poor signal. Perform network detection or connect to Ethernet or Wifi."
        ),
        "received": "2026-11-10T18:49:31-08:00",
        "read": True,
    }


def test_parse_message_received_fallbacks(messages, tz):
    item = copy.deepcopy(messages[0])
    del item["deviceSendTime"]
    assert parse_message(item, tz)["received"] == "2026-11-10T18:49:31-08:00"
    del item["displayTime"]
    # creationTime is UTC (02:49 UTC == 18:49 PST in the capture)
    assert parse_message(item, tz)["received"] == "2026-11-11T02:49:31+00:00"
    del item["creationTime"]
    assert parse_message(item, tz)["received"] is None
    item["readStatus"] = 0
    assert parse_message(item, tz)["read"] is False
    item["readStatus"] = None
    assert parse_message(item, tz)["read"] is None


def test_parse_messages_newest_first_and_skips_malformed(messages, tz, caplog):
    items = [*reversed(messages), {"title": "no id"}, {"id": "x"}]
    with caplog.at_level("DEBUG", logger="franklin_wh.messages"):
        parsed = parse_messages(items, tz)
    assert [m["id"] for m in parsed] == [6569334, 6565687, 6565683]
    assert caplog.text.count("malformed") == 2
    assert parse_messages([], tz) == []
    assert parse_messages(None, tz) == []


def test_truncate():
    assert truncate("short", 10) == "short"
    assert truncate("x" * 10, 10) == "x" * 10
    cut = truncate("y" * 11, 10)
    assert len(cut) == 10
    assert cut.endswith("…")


def test_parse_message_truncates(messages, tz):
    item = {**messages[0], "title": "t" * 400, "content": "c" * 2000}
    message = parse_message(item, tz)
    assert len(message["title"]) == MESSAGE_TITLE_MAX
    assert len(message["content"]) == MESSAGE_CONTENT_MAX


def test_new_messages(messages, tz):
    parsed = parse_messages(messages, tz)
    assert new_messages({6565683, 6565687, 6569334}, parsed) == []
    assert [m["id"] for m in new_messages({6565683}, parsed)] == [6565687, 6569334]
    assert [m["id"] for m in new_messages([], parsed)] == [6565683, 6565687, 6569334]


def test_latest_state_and_attributes(messages, tz):
    parsed = parse_messages(messages, tz)
    assert latest_title(parsed) == "4G signal is poor"
    attrs = latest_attributes(parsed)
    assert list(attrs) == [
        "id",
        "type",
        "sub_type",
        "content",
        "received",
        "read",
        "messages",
    ]
    assert attrs["id"] == 6569334
    assert attrs["messages"] == parsed
    json.dumps(attrs)  # serialisable without a default
    assert attribute_bytes(attrs) < ATTR_MAX_BYTES


def test_latest_empty():
    assert latest_title([]) is None
    attrs = latest_attributes([])
    assert attrs["id"] is None
    assert attrs["messages"] == []


def test_latest_attributes_budget(tz):
    items = [
        {
            "id": i,
            "title": "t" * 400,
            "type": 1,
            "subType": 1,
            "content": "c" * 2000,
            "readStatus": 1,
            "deviceSendTime": "2026-11-11 13:30:00",
        }
        for i in range(MESSAGE_LIST_SIZE)
    ]
    parsed = parse_messages(items, tz)
    assert len(parsed) == MESSAGE_LIST_SIZE
    # worst case: every title and content at its cap does not fit in 16 KB
    assert attribute_bytes({"messages": parsed}) > ATTR_MAX_BYTES
    attrs = latest_attributes(parsed)
    assert attribute_bytes(attrs) <= ATTR_MAX_BYTES
    # the newest stay, the oldest are dropped
    kept = [m["id"] for m in attrs["messages"]]
    assert 1 <= len(kept) < MESSAGE_LIST_SIZE
    assert kept == sorted(range(MESSAGE_LIST_SIZE), reverse=True)[: len(kept)]
    assert "fetched_at" not in attrs


def test_parse_messages_filters_other_gateways(messages, tz, caplog):
    mine = messages[0]["gatewayId"]
    items = [
        *messages,
        {**messages[0], "id": 9000001, "gatewayId": "10060010A01X99999999"},
        {**messages[0], "id": 9000002, "gatewayId": None},
        {k: v for k, v in messages[0].items() if k != "gatewayId"} | {"id": 9000003},
    ]
    # no gateway id: nothing filtered
    assert len(parse_messages(items, tz)) == len(items)
    with caplog.at_level("DEBUG", logger="franklin_wh.messages"):
        parsed = parse_messages(items, tz, mine)
    # the other gateway's item is skipped; items without a gatewayId are kept
    assert [m["id"] for m in parsed] == [9000003, 9000002, 6569334, 6565687, 6565683]
    assert "Skipping message 9000001 of gateway 10060010A01X99999999" in caplog.text


def test_diagnostics_messages(messages, tz):
    parsed = parse_messages(messages, tz)
    stripped = diagnostics_messages(parsed)
    assert len(stripped) == 3
    assert all("content" not in m for m in stripped)
    assert stripped[0]["title"] == "4G signal is poor"
