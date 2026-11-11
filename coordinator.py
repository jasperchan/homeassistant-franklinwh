"""DataUpdateCoordinator for FranklinWH."""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, tzinfo
import logging
import sys
from typing import Any, Final

from franklinwh import Client, ExportSettings, GridStatus, Mode, SmartCircuits, Stats

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .alarms import (
    AlarmInfo,
    AlarmTransition,
    alarm_attributes,
    diff_alarms,
    parse_alarms,
    sort_alarms,
)
from .api import (
    get_apowers_info,
    get_gateway_info,
    get_system_setting,
    get_warranty_info,
)
from .const import (
    ALARM_HISTORY_SIZE,
    COMPOSITE_GATE_TOLERANCE,
    COMPOSITE_MAX_FAILURES,
    COMPOSITE_MIN_INTERVAL,
    DEFAULT_LOCAL_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_ALARM,
    EVENT_MESSAGE,
    MANUFACTURER,
    MESSAGE_KNOWN_IDS_MAX,
    MESSAGE_LIST_SIZE,
    MESSAGES_UPDATE_INTERVAL,
    MODEL,
    SLOW_MAX_RETRIES,
    SLOW_RETRY_INTERVAL,
    SLOW_UPDATE_INTERVAL,
)
from .data import Message, MessageStats
from .messages import Message as ParsedMessage, new_messages, parse_messages
from .utils import get_client


def terminate(s: str) -> str:
    """Terminate a string with a period if it doesn't already have one."""
    if not s.endswith("."):
        s += "."
    return s


def format_message(message: Message) -> str:
    """Format the message for display."""
    r = f"{message['gatewayId']}: {terminate(message['title'])}\n{terminate(message['content'])}"
    if message["notice"]:
        r += f"\n{terminate(message['notice'])}"
    return r


@dataclass(frozen=True)
class FranklinWHSlowData:
    """Slowly changing data refreshed every SLOW_UPDATE_INTERVAL."""

    apowers: list[dict[str, Any]] | None = None  # obtainApowersInfo.result
    warranty: dict[str, Any] | None = None  # v2/warrantyInfo.result
    system_setting: dict[str, Any] | None = None  # getGatewaySystemSetting.result
    export: ExportSettings | None = None  # client.get_export_settings()
    gateway: dict[str, Any] | None = None  # get_home_gateway_list()[gateway]
    tou: dict[str, Any] | None = None  # client.get_tou_settings()
    updated_at: datetime | None = None  # last attempt (UTC)
    # member -> time of its last successful fetch (UTC)
    fetched_at: dict[str, datetime] = field(default_factory=dict)


SLOW_FETCHERS: Final[dict[str, Callable[[Client], Awaitable[Any]]]] = {
    "apowers": get_apowers_info,
    "warranty": get_warranty_info,
    "system_setting": get_system_setting,
    "export": lambda client: client.get_export_settings(),
    "gateway": get_gateway_info,
    # the library caches this for an hour and get_mode() reads it every poll,
    # so the slow-group call costs no extra cloud traffic
    "tou": lambda client: client.get_tou_settings(),
}
assert (
    tuple(SLOW_FETCHERS)
    == tuple(FranklinWHSlowData.__annotations__)[: len(SLOW_FETCHERS)]
), "SLOW_FETCHERS keys must match the FranklinWHSlowData members"


@dataclass(frozen=True)
class FranklinWHMessageList:
    """The latest push messages, newest first (see messages.parse_message)."""

    items: tuple[ParsedMessage, ...]
    fetched_at: datetime  # UTC


@dataclass
class FranklinWHData:
    """Statistics for FranklinWH."""

    # gather-fed, positional: the order matches FranklinWHCoordinator._data
    stats: Stats | None = None
    messages: MessageStats | None = None
    mode: Mode | None = None
    smart_circuits: SmartCircuits | None = None
    composite: dict[str, Any] | None = None
    # not gather-fed
    slow: FranklinWHSlowData | None = None
    alarms: tuple[AlarmInfo, ...] = ()
    composite_fetched_at: datetime | None = None  # last fresh composite (UTC)
    message_list: FranklinWHMessageList | None = None


class FranklinWHCoordinator(DataUpdateCoordinator[FranklinWHData]):
    """Fetch FranklinWH data.

    This class always produces stats, mode and optionally other attributes when enabled.
    """

    _data: Final = {
        "stats": "get_stats",
        "messages": "get_message_stats",
        "mode": "get_mode",
        "smart_circuits": "get_smart_circuits_enhanced",
        "composite": "get_composite_info",
    }
    assert list(_data) == list(FranklinWHData.__annotations__)[: len(_data)], (
        "_data keys must match the gather-fed FranklinWHData attributes"
    )
    # Attributes fetched through a coordinator adapter that never raises, so a
    # failure cannot count against _consecutive_failures or re-init the client.
    _TOLERANT: Final = frozenset({"composite"})

    @staticmethod
    async def disabled() -> None:
        """Placeholder for disabled method."""
        return

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        username: str,
        password: str,
        gateway_id: str,
        direct_host: str | None = None,
        max_failures: int = 3,
    ) -> None:
        """Initialize the coordinator."""
        if max_failures == -1:
            max_failures = sys.maxsize
        elif max_failures > 60:
            raise ValueError("max_failures must be between-1 (infinite) and 60")

        # Set update interval based on API type
        update_interval = (
            DEFAULT_LOCAL_SCAN_INTERVAL if direct_host else DEFAULT_SCAN_INTERVAL
        )

        super().__init__(
            hass,
            logging.getLogger(DOMAIN),
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
            # Keep entities available during temporary failures
            # Only mark unavailable after 3 consecutive failures (3 minutes)
            always_update=False,
        )

        # Store credentials for lazy client initialization
        self.username = username
        self.password = password
        self.gateway_id = gateway_id
        self.direct_host = direct_host
        self.client: Client = None  # type: ignore  # noqa: PGH003
        self._client_lock = asyncio.Lock()

        # Track consecutive failures
        self._consecutive_failures = 0
        self._max_failures = max_failures

        # Track dynamic stats
        self._methods = [self.disabled for _ in self._data]
        self._enabled = []

        # Composite info (rate gated, tolerant of failures)
        self._composite_last: dict[str, Any] | None = None
        self._composite_next: datetime | None = None
        self._composite_failures = 0
        self._composite_fresh = False
        self._composite_fetched_at: datetime | None = None

        # Slow group
        self._slow = FranklinWHSlowData()
        self._slow_next: datetime | None = None
        self._slow_failed: set[str] = set()
        self._slow_retries = 0  # consecutive SLOW_RETRY_INTERVAL rounds scheduled

        # Alarms
        self._tz: tzinfo = dt_util.get_default_time_zone()
        self._known_alarms: dict[int, AlarmInfo] = {}
        self._alarms_seeded = False
        self.alarm_history: deque[AlarmTransition] = deque(maxlen=ALARM_HISTORY_SIZE)

        # Push messages
        self._message_list: FranklinWHMessageList | None = None
        self._messages_next: datetime | None = None
        self._messages_unread: int | None = None  # unread count at the last fetch
        self._messages_failed = False
        self._known_message_ids: set[int] = set()
        self._messages_seeded = False

    def enable(self, *args: str) -> None:
        """Produce an attribute during data fetch."""
        for attr in args:
            if attr not in self._data:
                raise ValueError(f"Attribute '{attr}' is not a valid data attribute")
            if attr not in self._enabled:
                self._enabled.append(attr)
        for i, k in enumerate(self._data):
            if k in self._enabled:
                if k in self._TOLERANT:
                    self._methods[i] = getattr(self, f"_tolerant_{k}")
                else:
                    self._methods[i] = getattr(self.client, self._data[k])

    def device_info(self, entry: ConfigEntry) -> DeviceInfo:
        """Device info for the gateway device, with firmware/hardware versions."""
        gateway = self._slow.gateway or {}
        versions: dict[str, str] = {}
        # Only pass versions we know: a None would overwrite the registry value.
        if sw_version := gateway.get("version") or entry.data.get("sw_version"):
            versions["sw_version"] = sw_version
        if hw_version := gateway.get("realSysHdVersion"):
            versions["hw_version"] = hw_version
        return DeviceInfo(
            identifiers={(DOMAIN, self.gateway_id)},
            name=f"FranklinWH {self.gateway_id[-6:]}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            **versions,
        )

    def get_source(self, source: str, field: str | None = None) -> Any:
        """Return the data an entity reads from, ``None`` when unavailable.

        ``source`` is ``composite``, ``alarms``, ``slow`` or ``message_list``;
        for ``slow`` the ``field`` names the FranklinWHSlowData attribute.
        """
        data = self.data
        if data is None:
            return None
        match source:
            case "composite":
                return data.composite
            case "alarms":
                return data.alarms if data.composite is not None else None
            case "slow":
                if data.slow is None:
                    return None
                return getattr(data.slow, field) if field else data.slow
            case "message_list":
                return data.message_list.items if data.message_list else None
        raise ValueError(f"Unknown source '{source}'")

    def get_fetched_at(self, source: str, field: str | None = None) -> datetime | None:
        """Return when the data of ``get_source(source, field)`` was fetched."""
        data = self.data
        if data is None:
            return None
        match source:
            case "composite" | "alarms":
                return data.composite_fetched_at if data.composite else None
            case "slow":
                if data.slow is None or field is None:
                    return None
                return data.slow.fetched_at.get(field)
            case "message_list":
                return data.message_list.fetched_at if data.message_list else None
        raise ValueError(f"Unknown source '{source}'")

    async def _async_set_client(self) -> None:
        """Set the API client."""
        if self.client is None:
            async with self._client_lock:
                try:
                    _, self.client = await get_client(
                        self.hass,
                        self.username,
                        self.password,
                        self.gateway_id,
                        direct_connect_host=self.direct_host,
                    )
                except Exception as err:
                    raise UpdateFailed(f"Failed to initialize client: {err}") from err
                self.enable("stats", "messages", "mode", "composite")

    async def _tolerant_composite(self) -> dict[str, Any] | None:
        """Fetch composite info without ever raising (except auth errors).

        Rate gated to one real fetch per COMPOSITE_MIN_INTERVAL (the cloud
        answers code 429 on tight polling, and Direct Connect polls every 10 s).
        A poll within COMPOSITE_GATE_TOLERANCE of the gate counts as due so the
        cloud-mode schedule, which is exactly COMPOSITE_MIN_INTERVAL, cannot
        land a hair early and skip a whole cycle.
        Off-cycle polls and the first COMPOSITE_MAX_FAILURES - 1 failures reuse
        the previous payload; after that ``None`` makes composite-fed entities
        unavailable while stats entities are unaffected.
        """
        now = dt_util.utcnow()
        if (
            self._composite_next is not None
            and now < self._composite_next - COMPOSITE_GATE_TOLERANCE
        ):
            self._composite_fresh = False
            return self._composite_last

        self._composite_next = now + COMPOSITE_MIN_INTERVAL
        try:
            composite = await self.client.get_composite_info()
        except Exception as err:
            text = str(err).lower()
            if "auth" in text or "token" in text:
                raise
            self._composite_failures += 1
            self._composite_fresh = False
            log = (
                self.logger.warning
                if self._composite_failures == COMPOSITE_MAX_FAILURES
                else self.logger.debug
            )
            log(
                "Composite info error (attempt %d/%d): %r",
                self._composite_failures,
                COMPOSITE_MAX_FAILURES,
                err,
            )
            if self._composite_failures >= COMPOSITE_MAX_FAILURES:
                self._composite_last = None
            return self._composite_last

        self._composite_failures = 0
        self._composite_fresh = True
        self._composite_fetched_at = now
        self._composite_last = composite
        return composite

    async def _async_refresh_slow(self) -> FranklinWHSlowData:
        """Refresh the slow group when due; never raises.

        A full round fetches every member once per SLOW_UPDATE_INTERVAL. When
        members fail, only those are retried every SLOW_RETRY_INTERVAL, at
        most SLOW_MAX_RETRIES times in a row; after that the group falls back
        to the hourly cadence so a permanently broken endpoint cannot keep the
        whole group on a 5-minute loop.
        """
        now = dt_util.utcnow()
        if self._slow_next is not None and now < self._slow_next:
            return self._slow

        retry = self._slow_retries > 0
        members = {
            name: fetch(self.client)
            for name, fetch in SLOW_FETCHERS.items()
            if not retry or name in self._slow_failed
        }
        results = await asyncio.gather(*members.values(), return_exceptions=True)

        fetched_at = dict(self._slow.fetched_at)
        updates: dict[str, Any] = {"updated_at": now, "fetched_at": fetched_at}
        for name, result in zip(members, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                # warn once per member, debug while it keeps failing
                log = (
                    self.logger.debug
                    if name in self._slow_failed
                    else self.logger.warning
                )
                self._slow_failed.add(name)
                log("Failed to fetch %s: %r", name, result)
                continue
            self._slow_failed.discard(name)
            updates[name] = result
            fetched_at[name] = now

        self._slow = replace(self._slow, **updates)
        if self._slow_failed and self._slow_retries < SLOW_MAX_RETRIES:
            self._slow_retries += 1
            self._slow_next = now + SLOW_RETRY_INTERVAL
        else:
            self._slow_retries = 0
            self._slow_next = now + SLOW_UPDATE_INTERVAL

        if (gateway := self._slow.gateway) and (zone := gateway.get("zoneInfo")):
            try:
                self._tz = await dt_util.async_get_time_zone(zone) or self._tz
            except Exception as err:  # noqa: BLE001
                self.logger.debug("Invalid gateway time zone %r: %s", zone, err)
        return self._slow

    async def _async_refresh_messages(
        self, unread: int | None
    ) -> FranklinWHMessageList | None:
        """Refresh the push message list when due; never raises (except auth).

        Due every MESSAGES_UPDATE_INTERVAL, or at once when the per-poll
        unread count differs from the one seen at the last fetch, so a new
        message reaches the ``message`` event within one poll. The first list
        is stored silently; afterwards every id not seen before fires
        EVENT_MESSAGE on the bus (oldest first). A failed fetch keeps the
        previous list and is retried at the next due time.
        """
        now = dt_util.utcnow()
        if (
            self._messages_next is not None
            and now < self._messages_next
            and (unread is None or unread == self._messages_unread)
        ):
            return self._message_list

        self._messages_next = now + MESSAGES_UPDATE_INTERVAL
        self._messages_unread = unread
        try:
            items = await self.client.get_messages(MESSAGE_LIST_SIZE)
        except Exception as err:
            text = str(err).lower()
            if "auth" in text or "token" in text:
                raise
            log = self.logger.debug if self._messages_failed else self.logger.warning
            self._messages_failed = True
            log("Failed to fetch messages: %r", err)
            return self._message_list
        self._messages_failed = False

        messages = parse_messages(items, self._tz, self.gateway_id)
        if not self._messages_seeded:
            self._messages_seeded = True
        else:
            for message in new_messages(self._known_message_ids, messages):
                self.logger.info("Message received: %s", message["title"])
                self.hass.bus.async_fire(
                    EVENT_MESSAGE, {"gateway_id": self.gateway_id, **message}
                )
        ids = {m["id"] for m in messages}
        if len(self._known_message_ids) + len(ids) > MESSAGE_KNOWN_IDS_MAX:
            self._known_message_ids = ids
        else:
            self._known_message_ids |= ids
        self._message_list = FranklinWHMessageList(tuple(messages), now)
        return self._message_list

    def _bus_payload(self, transition: AlarmTransition) -> dict[str, Any]:
        """Payload of the EVENT_ALARM bus event."""
        return {
            "gateway_id": self.gateway_id,
            "action": transition.action,
            **{
                ("time" if key == "since" else key): value
                for key, value in alarm_attributes(transition.alarm).items()
            },
        }

    def _process_alarms(
        self, composite: dict[str, Any] | None
    ) -> tuple[AlarmInfo, ...]:
        """Diff the active alarms against the last fresh set; never raises.

        Stale or absent composite data keeps the previous alarms and emits no
        transition. The first fresh set is stored silently so an HA restart
        does not replay "raised" for long-standing alarms.
        """
        previous = self.data.alarms if self.data is not None else ()
        if (
            not self._composite_fresh
            or composite is None
            or composite.get("currentAlarmVOList") is None
        ):
            return previous

        at = dt_util.utcnow()
        try:
            current = parse_alarms(composite, self._tz, at, self._known_alarms)
        except Exception as err:  # noqa: BLE001
            self.logger.warning("Failed to parse alarms: %r", err)
            return previous

        if not self._alarms_seeded:
            self._alarms_seeded = True
        else:
            for transition in diff_alarms(self._known_alarms, current, at):
                self.alarm_history.append(transition)
                self.logger.info(
                    "Alarm %s: %s (%s)",
                    transition.action,
                    transition.alarm.name,
                    transition.alarm.code,
                )
                self.hass.bus.async_fire(EVENT_ALARM, self._bus_payload(transition))
        self._known_alarms = current
        return sort_alarms(current)

    async def _async_update_data(self) -> FranklinWHData:
        """Fetch data from FranklinWH API."""
        try:
            # Initialize client on first run (in executor to avoid blocking)
            await self._async_set_client()

            # Fetch data attributes
            tasks = [function() for function in self._methods]
            results = await asyncio.gather(*tasks)

            # Reset failure counter on success
            self._consecutive_failures = 0

            data = FranklinWHData(*results)
            data.slow = await self._async_refresh_slow()
            data.alarms = self._process_alarms(data.composite)
            data.composite_fetched_at = (
                self._composite_fetched_at if data.composite is not None else None
            )
            data.message_list = await self._async_refresh_messages(
                getattr(data.messages, "unread", None)
            )
            return data

        except Exception as err:
            text = str(err).lower()
            # Check if it's an authentication-related error
            if "auth" in text or "token" in text:
                raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

            # Increment failure counter
            self._consecutive_failures += 1
            self.logger.warning(
                "API error (attempt %d/%d): %s",
                self._consecutive_failures,
                self._max_failures,
                err,
            )

            # Only raise UpdateFailed after max failures
            if self._consecutive_failures >= self._max_failures:
                self.logger.error(
                    "Max consecutive failures reached, marking unavailable"
                )
                self.client = None  # force reinitialization on next update
                raise UpdateFailed(f"Error communicating with API: {err}") from err

            # Return last known data to keep entities available
            if self.data:
                self.logger.debug("Returning last known data due to temporary failure")
                return self.data
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_set(self, func, *args: Any, **kwargs: Any) -> None:
        """Generic setter to call client methods and refresh data."""
        sleep = kwargs.pop("sleep", 7)
        value = kwargs.pop("value", "value")
        try:
            await func(*args, **kwargs)
            await asyncio.sleep(sleep)
            await self.async_request_refresh()
        except Exception:
            self.logger.exception("Failed to set %s", value)
            raise

    async def async_set_generator(self, enabled: bool) -> None:
        """Set the generator."""
        await self.async_set(self.client.set_generator, enabled, value="generator")

    async def async_set_grid_status(self, status: GridStatus) -> None:
        """Set the grid connection."""
        await self.async_set(self.client.set_grid_status, status, value="grid status")

    async def async_set_circuit(self, index: int, on: bool) -> None:
        """Set a specific circuit."""
        await self.async_set(
            self.client.set_circuit, index, on, value="circuit state", sleep=1
        )

    async def async_set_mode(self, value: str) -> None:
        """Set the operating mode."""
        mode = await self.client.get_mode_by_name(value)
        await self.async_set(self.client.set_mode, mode, value="mode")

    async def async_set_backup_reserve(self, soc: int) -> None:
        """Set the backup reserve."""
        await self.async_set(
            self.client.set_backup_reserve, soc, value="backup reserve"
        )

    async def async_get_messages(self, count: int) -> list[str]:
        """Get the latest messages from the system."""
        try:
            await self._async_set_client()
            messages = await self.client.get_messages(count)
            self.logger.debug("Retrieved %d messages", len(messages))
            return [format_message(msg) for msg in messages]
        except Exception:
            self.logger.exception("Failed to get messages")
            raise

    # Map string operation_mode to Mode factory methods
    _operation_modes: Final[dict[str, callable[None, Mode]]] = {
        "self_use": Mode.self_consumption,
        "backup": Mode.emergency_backup,
        "time_of_use": Mode.time_of_use,
        # Note: clean_backup mode from Home Assistant services.yaml
        # Maps to emergency_backup as the library doesn't have a separate clean_backup mode
        "clean_backup": Mode.emergency_backup,
    }

    async def async_set_operation_mode(self, mode: str) -> None:
        """Set the operation mode of the system."""
        # Each mode gets a default reserve of 20% except emergency_backup (100%)

        if mode not in self._operation_modes:
            raise ValueError(f"Invalid mode: {mode}")

        # Create mode object with default SOC
        mode_obj = self._operation_modes[mode]()

        try:
            # Set the mode via API (async method in franklinwh 1.0.0+)
            await self.client.set_mode(mode_obj)
        except Exception:
            self.logger.exception("Failed to set operation mode to %s", mode)
            raise

        # Request immediate refresh
        await self.async_request_refresh()
        self.logger.info("Successfully set operation mode to %s", mode)

    async def async_set_battery_reserve(self, reserve_percent: int) -> None:
        """Set the battery reserve percentage.

        This attempts to preserve the current operation mode while updating
        the battery reserve (SOC) percentage. If the current mode cannot be
        determined, it defaults to self_consumption mode.
        """
        try:
            await self.client.set_backup_reserve(reserve_percent)

            # Request immediate refresh
            await self.async_request_refresh()
            self.logger.info(
                "Successfully set battery reserve to %d%%", reserve_percent
            )
        except Exception:
            self.logger.exception(
                "Failed to set battery reserve to %d%%", reserve_percent
            )
            raise
