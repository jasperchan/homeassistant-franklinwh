"""Coordinator tests with a fake client (stubbed Home Assistant)."""

import copy
from datetime import timedelta
from typing import Any
import zoneinfo

from conftest import GATEWAY_ID, T0, Clock, FranklinWHCoordinator, load_fixture, run
from franklin_wh.const import (
    COMPOSITE_GATE_TOLERANCE,
    COMPOSITE_MAX_FAILURES,
    COMPOSITE_MIN_INTERVAL,
    EVENT_ALARM,
    EVENT_MESSAGE,
    MESSAGE_LIST_SIZE,
    MESSAGES_UPDATE_INTERVAL,
    SLOW_MAX_RETRIES,
    SLOW_RETRY_INTERVAL,
    SLOW_UPDATE_INTERVAL,
)
from franklin_wh.coordinator import FranklinWHData
from franklinwh import ExportMode
import pytest


def composite_with(alarms: list[dict[str, Any]]) -> dict[str, Any]:
    composite = copy.deepcopy(load_fixture("composite.json"))
    composite["currentAlarmVOList"] = alarms
    return composite


def alarm_item(
    alarm_id: int, code: str = "5144", since: str = "2026-11-10 15:01:30"
) -> dict:
    return {
        "id": alarm_id,
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


def poll(
    coordinator: FranklinWHCoordinator, clock: Clock, *composites: Any
) -> FranklinWHData:
    """Advance one update interval per composite and refresh."""
    for item in composites:
        coordinator.client.composite_queue.append(item)
        clock.advance(COMPOSITE_MIN_INTERVAL)
        run(coordinator.async_refresh())
    assert coordinator.data is not None
    return coordinator.data


def test_first_refresh_seeds_alarms_silently(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())

    data = coordinator.data
    assert coordinator.last_update_success
    assert data.stats == {"stats": True}
    assert data.composite["deviceStatus"] == 1
    assert [a.id for a in data.alarms] == [2756389132]
    assert data.alarms[0].since.isoformat() == "2026-11-10T15:01:30-08:00"
    assert coordinator._tz == zoneinfo.ZoneInfo("America/Los_Angeles")
    coordinator.hass.bus.async_fire.assert_not_called()
    assert list(coordinator.alarm_history) == []

    # slow group ran inside the first refresh
    assert data.slow.apowers[0]["soc"] == 9.5
    assert data.slow.warranty["remainThroughput"] == 59967.82
    assert data.slow.system_setting["rsdEnable"] == 1
    assert data.slow.export.mode is ExportMode.SOLAR_AND_APOWER
    assert data.slow.gateway["version"] == "V10R11B60D00_SYS_aP1X_20_2S_AHUB"
    assert data.slow.updated_at == T0
    assert coordinator._slow_next == T0 + SLOW_UPDATE_INTERVAL
    assert coordinator._composite_next == T0 + COMPOSITE_MIN_INTERVAL


def test_device_info_versions(coordinator, client, clock):
    from homeassistant.config_entries import ConfigEntry

    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    info = coordinator.device_info(ConfigEntry())
    assert info["identifiers"] == {("franklin_wh", GATEWAY_ID)}
    assert info["name"] == "FranklinWH 000001"
    assert info["sw_version"] == "V10R11B60D00_SYS_aP1X_20_2S_AHUB"
    assert info["hw_version"] == "FranklinWH System1.5"


def test_composite_failure_does_not_count_against_stats(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())

    for n in range(1, COMPOSITE_MAX_FAILURES):
        poll(coordinator, clock, KeyError("result"))  # the 429 body has no result
        assert coordinator.last_update_success
        assert coordinator._consecutive_failures == 0
        assert coordinator._composite_failures == n
        assert coordinator.data.composite is not None, "previous composite reused"
        assert coordinator.data.stats == {"stats": True}
        assert [a.id for a in coordinator.data.alarms] == [2756389132]

    poll(coordinator, clock, RuntimeError("Too Many Requests"))
    assert coordinator.last_update_success
    assert coordinator._consecutive_failures == 0
    assert coordinator.data.composite is None
    assert coordinator.data.stats == {"stats": True}
    assert coordinator.client is client, "client must not be re-initialised"
    # alarms are retained for when composite comes back; entities go unavailable
    assert [a.id for a in coordinator.data.alarms] == [2756389132]
    assert coordinator.get_source("alarms") is None
    assert coordinator.get_source("composite") is None
    coordinator.hass.bus.async_fire.assert_not_called()

    # recovery: no replay of the still-active alarm
    poll(coordinator, clock, load_fixture("composite.json"))
    assert coordinator.data.composite is not None
    assert coordinator._composite_failures == 0
    coordinator.hass.bus.async_fire.assert_not_called()


def test_composite_auth_error_propagates(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    clock.advance(COMPOSITE_MIN_INTERVAL)
    client.composite_queue.append(RuntimeError("invalid token"))
    run(coordinator.async_refresh())
    assert not coordinator.last_update_success
    assert type(coordinator.last_exception).__name__ == "ConfigEntryAuthFailed"


def test_composite_rate_gate(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    assert client.composite_calls == 1

    # Direct Connect style 10 s polls: no new fetch, no diff, previous reused
    client.composite_queue.append(composite_with([]))  # would clear if fetched
    for _ in range(5):
        clock.advance(timedelta(seconds=10))
        run(coordinator.async_refresh())
        assert client.composite_calls == 1
        assert coordinator._composite_fresh is False
        assert [a.id for a in coordinator.data.alarms] == [2756389132]
    coordinator.hass.bus.async_fire.assert_not_called()

    clock.advance(timedelta(seconds=10))
    run(coordinator.async_refresh())
    assert client.composite_calls == 2
    assert coordinator.data.alarms == ()
    coordinator.hass.bus.async_fire.assert_called_once()


def test_composite_gate_tolerates_early_poll(coordinator, client, clock):
    # HA schedules cloud polls exactly COMPOSITE_MIN_INTERVAL apart; a poll a
    # few milliseconds early must still fetch, not skip a whole cycle
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    assert client.composite_calls == 1

    client.composite_queue.append(load_fixture("composite.json"))
    clock.advance(COMPOSITE_MIN_INTERVAL - timedelta(milliseconds=5))
    run(coordinator.async_refresh())
    assert client.composite_calls == 2
    assert coordinator._composite_fresh is True
    assert coordinator._composite_next == clock.now + COMPOSITE_MIN_INTERVAL

    # but a poll clearly inside the window is still gated
    client.composite_queue.append(load_fixture("composite.json"))
    clock.advance(
        COMPOSITE_MIN_INTERVAL - COMPOSITE_GATE_TOLERANCE - timedelta(seconds=1)
    )
    run(coordinator.async_refresh())
    assert client.composite_calls == 2
    assert coordinator._composite_fresh is False


def test_alarm_transitions_fire_bus_events(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    bus = coordinator.hass.bus

    # same alarm again: nothing
    poll(coordinator, clock, load_fixture("composite.json"))
    bus.async_fire.assert_not_called()

    # cleared
    poll(coordinator, clock, composite_with([]))
    bus.async_fire.assert_called_once()
    event_type, payload = bus.async_fire.call_args.args
    assert event_type == EVENT_ALARM
    assert payload == {
        "gateway_id": GATEWAY_ID,
        "action": "cleared",
        "id": 2756389132,
        "code": "5144",
        "common_code": "5#44",
        "name": "NO.1 MPPT The arc lock fault occurs",
        "level": 2,
        "time": "2026-11-10T15:01:30-08:00",
        "equipment_sn": "10050019A00X00000001",
        "explanation": (
            "The arcing fault of the PV branch x has been triggered multiple "
            "times . Alarm trigger condition: 5 occurrences of an MPPT PV arc "
            "fault within 24 hours."
        ),
        "plan": (
            "1、Check all connection points for the corresponding MPPT PV string "
            "cables to ensure there is no poor contact.\n2、If the PV string power "
            "cable connections are secure, please clear the fault via the app.\n"
            "3、If the fault persists, please contact support at "
            "service@franklinwh.com."
        ),
    }
    assert coordinator.data.alarms == ()
    assert [t.action for t in coordinator.alarm_history] == ["cleared"]
    assert coordinator.alarm_history[0].at == clock.now

    # re-occurrence with a new id and a new raised alarm: raised first, by since
    bus.async_fire.reset_mock()
    poll(
        coordinator,
        clock,
        composite_with(
            [
                alarm_item(3, "1001", since="2026-11-11 12:30:00"),
                alarm_item(2, since="2026-11-11 12:00:00"),
            ]
        ),
    )
    actions = [
        (c.args[1]["action"], c.args[1]["id"]) for c in bus.async_fire.call_args_list
    ]
    assert actions == [("raised", 2), ("raised", 3)]
    assert [a.id for a in coordinator.data.alarms] == [2, 3]

    bus.async_fire.reset_mock()
    poll(
        coordinator,
        clock,
        composite_with([alarm_item(3, "1001", since="2026-11-11 12:30:00")]),
    )
    actions = [
        (c.args[1]["action"], c.args[1]["id"]) for c in bus.async_fire.call_args_list
    ]
    assert actions == [("cleared", 2)]
    assert [t.action for t in coordinator.alarm_history] == [
        "cleared",
        "raised",
        "raised",
        "cleared",
    ]


def test_relogged_alarm_ids_do_not_flap(coordinator, client, clock):
    # 2026-11-12 live sequence: two active alarms, each re-logged under a new
    # id (and later a new time) on consecutive polls, then one really clears
    client.composite_queue.append(
        composite_with(
            [
                alarm_item(2761788245, "6112", since="2026-11-12 09:34:37"),
                alarm_item(2761788247, since="2026-11-12 09:34:37"),
            ]
        )
    )
    run(coordinator.async_refresh())
    bus = coordinator.hass.bus

    for ids in ((2761799410, 2761799411), (2761806677, 2761806678)):
        poll(
            coordinator,
            clock,
            composite_with(
                [
                    alarm_item(ids[0], "6112", since="2026-11-12 09:34:37"),
                    alarm_item(ids[1], since="2026-11-12 09:34:37"),
                ]
            ),
        )
    poll(
        coordinator,
        clock,
        composite_with(
            [
                alarm_item(2761815606, "6112", since="2026-11-12 09:44:16"),
                alarm_item(2761815607, since="2026-11-12 09:44:16"),
            ]
        ),
    )
    bus.async_fire.assert_not_called()
    assert [(a.code, a.id) for a in coordinator.data.alarms] == [
        ("6112", 2761815606),
        ("5144", 2761815607),
    ]
    assert {a.since.isoformat() for a in coordinator.data.alarms} == {
        "2026-11-12T09:34:37-08:00"
    }

    # 6112 really clears while 5144 is re-logged once more
    poll(
        coordinator,
        clock,
        composite_with([alarm_item(2761924701, since="2026-11-12 09:54:07")]),
    )
    bus.async_fire.assert_called_once()
    payload = bus.async_fire.call_args.args[1]
    assert (payload["action"], payload["code"], payload["id"]) == (
        "cleared",
        "6112",
        2761815606,
    )
    assert [(a.code, a.id) for a in coordinator.data.alarms] == [("5144", 2761924701)]


def test_missing_alarm_list_is_not_a_clear(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    composite = load_fixture("composite.json")
    del composite["currentAlarmVOList"]
    poll(coordinator, clock, composite)
    assert [a.id for a in coordinator.data.alarms] == [2756389132]
    coordinator.hass.bus.async_fire.assert_not_called()


def test_slow_group_partial_failure_retries(coordinator, client, clock):
    client.fail_paths.add("hes-gateway/terminal/v2/warrantyInfo")
    client.gateway_list_error = RuntimeError("offline")
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())

    slow = coordinator.data.slow
    assert slow.apowers is not None
    assert slow.system_setting is not None
    assert slow.export is not None
    assert slow.warranty is None
    assert slow.gateway is None
    assert coordinator._slow_next == T0 + SLOW_RETRY_INTERVAL
    # without the gateway entry alarms are parsed in the default zone
    assert coordinator.data.alarms[0].since.tzinfo == zoneinfo.ZoneInfo("UTC")

    # not due yet: nothing re-fetched
    calls = len(client.get_calls)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert len(client.get_calls) == calls

    # due: only the failed members are re-fetched, the others keep their values
    client.fail_paths.clear()
    client.gateway_list_error = None
    client.get_calls.clear()
    clock.advance(SLOW_RETRY_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert client.get_calls == ["hes-gateway/terminal/v2/warrantyInfo"]
    slow = coordinator.data.slow
    assert slow.warranty["remainThroughput"] == 59967.82
    assert slow.gateway["id"] == GATEWAY_ID
    assert slow.apowers is not None
    assert slow.updated_at == clock.now
    assert coordinator._slow_next == clock.now + SLOW_UPDATE_INTERVAL
    assert coordinator._slow_retries == 0

    # the next full round fetches everything again
    client.get_calls.clear()
    clock.advance(SLOW_UPDATE_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert len(client.get_calls) == 3


def test_slow_group_retry_is_capped(coordinator, client, clock):
    client.fail_paths.add("hes-gateway/terminal/v2/warrantyInfo")
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    assert coordinator.data.slow.warranty is None
    assert coordinator.data.slow.apowers is not None

    # SLOW_MAX_RETRIES retry rounds, each fetching only the failing member
    for n in range(1, SLOW_MAX_RETRIES + 1):
        assert coordinator._slow_next == clock.now + SLOW_RETRY_INTERVAL
        assert coordinator._slow_retries == n
        client.get_calls.clear()
        clock.advance(SLOW_RETRY_INTERVAL)
        poll(coordinator, clock, load_fixture("composite.json"))
        assert client.get_calls == ["hes-gateway/terminal/v2/warrantyInfo"]
        assert coordinator.data.slow.warranty is None
        assert coordinator.data.slow.apowers is not None

    # retries exhausted: back to the hourly cadence, next round is a full one
    assert coordinator._slow_retries == 0
    assert coordinator._slow_next == clock.now + SLOW_UPDATE_INTERVAL
    client.get_calls.clear()
    clock.advance(SLOW_UPDATE_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert len(client.get_calls) == 3
    assert coordinator._slow_retries == 1
    assert coordinator._slow_next == clock.now + SLOW_RETRY_INTERVAL


def test_alarm_with_null_time_is_tracked(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    bus = coordinator.hass.bus

    item = {**alarm_item(7, "1234"), "time": None}
    poll(coordinator, clock, composite_with([alarm_item(2756389132), item]))
    raised_at = clock.now
    assert [a.id for a in coordinator.data.alarms] == [2756389132, 7]
    assert coordinator.data.alarms[1].since == raised_at
    bus.async_fire.assert_called_once()
    assert bus.async_fire.call_args.args[1]["time"] == raised_at.isoformat()

    # since does not drift on the next poll
    bus.async_fire.reset_mock()
    poll(coordinator, clock, composite_with([alarm_item(2756389132), item]))
    assert coordinator.data.alarms[1].since == raised_at
    bus.async_fire.assert_not_called()

    poll(coordinator, clock, composite_with([alarm_item(2756389132)]))
    assert [a.id for a in coordinator.data.alarms] == [2756389132]
    assert bus.async_fire.call_args.args[1]["action"] == "cleared"


def test_slow_group_failure_keeps_previous_value(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    assert coordinator.data.slow.warranty is not None

    client.fail_paths.add("hes-gateway/terminal/v2/warrantyInfo")
    clock.advance(SLOW_UPDATE_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert coordinator.data.slow.warranty["remainThroughput"] == 59967.82
    assert coordinator._slow_next == clock.now + SLOW_RETRY_INTERVAL


def test_get_source(coordinator, client, clock):
    assert coordinator.get_source("composite") is None
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    assert coordinator.get_source("composite")["deviceStatus"] == 1
    assert len(coordinator.get_source("alarms")) == 1
    assert coordinator.get_source("slow", "warranty")["throughput"] == 60
    assert coordinator.get_source("slow").export.mode is ExportMode.SOLAR_AND_APOWER
    with pytest.raises(ValueError):
        coordinator.get_source("nope")


def bus_events(coordinator: FranklinWHCoordinator, event_type: str) -> list[dict]:
    """Payloads of the bus events of one type fired so far."""
    return [
        c.args[1]
        for c in coordinator.hass.bus.async_fire.call_args_list
        if c.args[0] == event_type
    ]


def message_item(message_id: int, title: str = "new") -> dict[str, Any]:
    return {
        "id": message_id,
        "title": title,
        "type": 1,
        "subType": 2,
        "gatewayId": GATEWAY_ID,
        "content": f"content of {message_id}",
        "readStatus": 0,
        "creationTime": "2026-11-11 21:30:00",
        "deviceSendTime": "2026-11-11 13:30:00",
        "displayTime": "2026-11-11 13:30:00",
    }


def test_first_refresh_seeds_messages_and_fetch_times(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    data = coordinator.data

    assert client.messages_calls == [MESSAGE_LIST_SIZE]
    assert [m["id"] for m in data.message_list.items] == [6569334, 6565687, 6565683]
    assert data.message_list.items[0]["received"] == "2026-11-10T18:49:31-08:00"
    assert data.message_list.fetched_at == T0
    assert coordinator._messages_next == T0 + MESSAGES_UPDATE_INTERVAL
    assert bus_events(coordinator, EVENT_MESSAGE) == []

    # tou joined the slow group; every member records its fetch time
    assert data.slow.tou["currendId"] == 218933
    assert data.slow.fetched_at == dict.fromkeys(
        ["apowers", "warranty", "system_setting", "export", "gateway", "tou"], T0
    )
    assert data.composite_fetched_at == T0
    assert coordinator.get_fetched_at("composite") == T0
    assert coordinator.get_fetched_at("alarms") == T0
    assert coordinator.get_fetched_at("slow", "warranty") == T0
    assert coordinator.get_fetched_at("slow") is None
    assert coordinator.get_fetched_at("message_list") == T0
    assert coordinator.get_source("message_list") == data.message_list.items
    with pytest.raises(ValueError):
        coordinator.get_fetched_at("nope")


def test_message_cadence_and_events(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    first = coordinator.data.message_list

    # a new message appears but the list is not due: nothing fetched
    client.messages.insert(0, message_item(7000001, "first new"))
    polls = int(MESSAGES_UPDATE_INTERVAL / COMPOSITE_MIN_INTERVAL) - 1
    for _ in range(polls):
        poll(coordinator, clock, load_fixture("composite.json"))
        assert client.messages_calls == [MESSAGE_LIST_SIZE]
        assert coordinator.data.message_list is first
    assert bus_events(coordinator, EVENT_MESSAGE) == []

    # due: fetched, the new id fires one bus event with the message dict
    poll(coordinator, clock, load_fixture("composite.json"))
    assert client.messages_calls == [MESSAGE_LIST_SIZE] * 2
    assert bus_events(coordinator, EVENT_MESSAGE) == [
        {
            "gateway_id": GATEWAY_ID,
            "id": 7000001,
            "title": "first new",
            "type": 1,
            "sub_type": 2,
            "content": "content of 7000001",
            "received": "2026-11-11T13:30:00-08:00",
            "read": False,
        }
    ]
    assert coordinator.data.message_list.items[0]["id"] == 7000001
    assert coordinator.data.message_list.fetched_at == clock.now
    assert bus_events(coordinator, EVENT_ALARM) == []

    # the same list again: no replay
    clock.advance(MESSAGES_UPDATE_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert len(bus_events(coordinator, EVENT_MESSAGE)) == 1

    # several new messages fire oldest first
    client.messages.insert(0, message_item(7000003, "third"))
    client.messages.insert(0, message_item(7000002, "second"))
    clock.advance(MESSAGES_UPDATE_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert [e["id"] for e in bus_events(coordinator, EVENT_MESSAGE)] == [
        7000001,
        7000002,
        7000003,
    ]


def test_messages_of_other_gateways_are_ignored(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())

    # the list endpoint is account-level: another gateway's message must not
    # fire this gateway's event nor show in its list
    other = {**message_item(7000001, "elsewhere"), "gatewayId": "10060010A01X99999999"}
    client.messages.insert(0, other)
    client.messages.insert(0, message_item(7000002, "here"))
    clock.advance(MESSAGES_UPDATE_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert [e["id"] for e in bus_events(coordinator, EVENT_MESSAGE)] == [7000002]
    assert 7000001 not in {m["id"] for m in coordinator.data.message_list.items}


def test_unread_count_change_fetches_messages_early(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())

    client.messages.insert(0, message_item(7000001))
    client.unread = 1
    poll(coordinator, clock, load_fixture("composite.json"))
    assert client.messages_calls == [MESSAGE_LIST_SIZE] * 2
    assert [e["id"] for e in bus_events(coordinator, EVENT_MESSAGE)] == [7000001]
    assert coordinator._messages_next == clock.now + MESSAGES_UPDATE_INTERVAL

    # unchanged count: back to the normal cadence
    poll(coordinator, clock, load_fixture("composite.json"))
    assert client.messages_calls == [MESSAGE_LIST_SIZE] * 2

    # reading messages in the app (count drops) also refreshes the list
    client.unread = 0
    poll(coordinator, clock, load_fixture("composite.json"))
    assert client.messages_calls == [MESSAGE_LIST_SIZE] * 3
    assert len(bus_events(coordinator, EVENT_MESSAGE)) == 1


def test_message_fetch_failure_keeps_previous_list(coordinator, client, clock, caplog):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    first = coordinator.data.message_list

    client.messages_error = RuntimeError("boom")
    with caplog.at_level("DEBUG", logger="franklin_wh"):
        clock.advance(MESSAGES_UPDATE_INTERVAL)
        poll(coordinator, clock, load_fixture("composite.json"))
        clock.advance(MESSAGES_UPDATE_INTERVAL)
        poll(coordinator, clock, load_fixture("composite.json"))
    assert coordinator.last_update_success
    assert coordinator._consecutive_failures == 0
    assert coordinator.data.message_list is first, "previous list reused"
    assert coordinator.data.stats == {"stats": True}
    levels = [
        r.levelname for r in caplog.records if "Failed to fetch messages" in r.message
    ]
    assert levels == ["WARNING", "DEBUG"]

    # recovery, still no replay of the seeded messages
    client.messages_error = None
    clock.advance(MESSAGES_UPDATE_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    assert coordinator.data.message_list.fetched_at == clock.now
    assert bus_events(coordinator, EVENT_MESSAGE) == []


def test_message_auth_error_propagates(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    client.messages_error = RuntimeError("token expired")
    clock.advance(MESSAGES_UPDATE_INTERVAL)
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    assert not coordinator.last_update_success
    assert type(coordinator.last_exception).__name__ == "ConfigEntryAuthFailed"


def test_slow_fetched_at_tracks_members(coordinator, client, clock):
    client.fail_paths.add("hes-gateway/terminal/v2/warrantyInfo")
    client.tou_error = RuntimeError("offline")
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    fetched_at = coordinator.data.slow.fetched_at
    assert "warranty" not in fetched_at
    assert "tou" not in fetched_at
    assert fetched_at["apowers"] == T0
    assert coordinator.get_fetched_at("slow", "tou") is None
    assert coordinator.data.slow.tou is None

    client.fail_paths.clear()
    client.tou_error = None
    clock.advance(SLOW_RETRY_INTERVAL)
    poll(coordinator, clock, load_fixture("composite.json"))
    fetched_at = coordinator.data.slow.fetched_at
    assert fetched_at["apowers"] == T0
    assert fetched_at["warranty"] == clock.now
    assert fetched_at["tou"] == clock.now
    assert coordinator.data.slow.tou["currendId"] == 218933


def test_composite_fetched_at_follows_freshness(coordinator, client, clock):
    client.composite_queue.append(load_fixture("composite.json"))
    run(coordinator.async_refresh())
    assert coordinator.data.composite_fetched_at == T0

    # gated poll reuses the payload and its fetch time (nothing is fetched)
    clock.advance(timedelta(seconds=10))
    run(coordinator.async_refresh())
    assert coordinator.data.composite_fetched_at == T0

    for _ in range(COMPOSITE_MAX_FAILURES):
        poll(coordinator, clock, RuntimeError("429"))
    assert coordinator.data.composite is None
    assert coordinator.data.composite_fetched_at is None
    assert coordinator.get_fetched_at("composite") is None

    poll(coordinator, clock, load_fixture("composite.json"))
    assert coordinator.data.composite_fetched_at == clock.now


def test_data_contract():
    """The gather-fed fields stay positional and in _data order."""
    assert list(FranklinWHCoordinator._data) == [
        "stats",
        "messages",
        "mode",
        "smart_circuits",
        "composite",
    ]
    data = FranklinWHData(1, 2, 3, 4, {"x": 1})
    assert (data.stats, data.messages, data.mode, data.smart_circuits) == (1, 2, 3, 4)
    assert data.composite == {"x": 1}
    assert data.slow is None
    assert data.alarms == ()
    assert data.composite_fetched_at is None
    assert data.message_list is None
