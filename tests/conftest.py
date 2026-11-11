"""Test setup: load the integration as ``franklin_wh`` without Home Assistant.

The integration files live at the repo root. A synthetic ``franklin_wh``
package pointing at the root lets ``import franklin_wh.alarms`` resolve the
relative imports without executing ``__init__.py``. The handful of
``homeassistant``/``franklinwh`` modules the coordinator imports are stubbed
only when the real ones are not importable, so the same tests run inside an
HA dev environment.

Run from the repo root with ``python3 -P -m pytest -q tests`` (or plain
``pytest -q tests``): ``-P`` keeps the repo root off ``sys.path`` so the
integration's ``select.py`` does not shadow the stdlib ``select`` module.
"""

import asyncio
import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
import importlib
from importlib.machinery import ModuleSpec
import importlib.util
import json
import logging
from pathlib import Path
import sys
import types
from typing import Any, ClassVar
from unittest.mock import MagicMock
import zoneinfo

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _missing(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is None
    except (ImportError, ValueError):
        return True


def _module(name: str, is_package: bool = False, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    # a __spec__ keeps traceback formatting (3.15) and importlib.resources happy
    module.__spec__ = ModuleSpec(name, None, is_package=is_package)
    if is_package:
        module.__path__ = []
    sys.modules[name] = module
    return module


def _package(name: str, **attrs: Any) -> types.ModuleType:
    return _module(name, is_package=True, **attrs)


# --- franklinwh stubs --------------------------------------------------------

if _missing("franklinwh"):

    class ExportMode(Enum):
        """Mirror of franklinwh.ExportMode."""

        SOLAR_ONLY = 1
        SOLAR_AND_APOWER = 2
        NO_EXPORT = 3

    @dataclass(frozen=True)
    class ExportSettings:
        """Mirror of franklinwh.ExportSettings."""

        mode: ExportMode
        limit_kw: float | None = None

    class _Placeholder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class HttpClientFactory(_Placeholder):
        @staticmethod
        def set_client_factory(factory: Any) -> None:
            pass

    class Mode(_Placeholder):
        """Mirror of the franklinwh.Mode factory methods the coordinator binds."""

        @classmethod
        def self_consumption(cls, *args: Any, **kwargs: Any) -> "Mode":
            return cls()

        @classmethod
        def emergency_backup(cls, *args: Any, **kwargs: Any) -> "Mode":
            return cls()

        @classmethod
        def time_of_use(cls, *args: Any, **kwargs: Any) -> "Mode":
            return cls()

    class _Accessory:
        def __init__(self, accessory_id: int) -> None:
            self.id = accessory_id

    class AccessoryType:
        """Mirror of the two franklinwh.AccessoryType members sensor.py reads."""

        GENERATOR_MODULE = _Accessory(1)
        SMART_CIRCUITS_MODULE = _Accessory(2)

    class _RunStatus:
        def __init__(self, title: str) -> None:
            self.title = title

    class RunStatus:
        """Mirror of franklinwh.RunStatus."""

        STANDBY = _RunStatus("Standby")
        CHARGING = _RunStatus("Charging")
        DISCHARGING = _RunStatus("Discharging")

        @classmethod
        def titles(cls) -> list[str]:
            return ["Standby", "Charging", "Discharging"]

    _package(
        "franklinwh",
        AccessoryType=AccessoryType,
        RunStatus=RunStatus,
        Client=type("Client", (_Placeholder,), {}),
        GridStatus=Enum("GridStatus", {"NORMAL": 1, "OFF": 2}),
        Mode=Mode,
        SmartCircuits=type("SmartCircuits", (_Placeholder,), {}),
        Stats=type("Stats", (_Placeholder,), {}),
        TokenFetcher=type("TokenFetcher", (_Placeholder,), {}),
        HttpClientFactory=HttpClientFactory,
        ExportMode=ExportMode,
        ExportSettings=ExportSettings,
    )

if _missing("franklinwh_direct_or_cloud"):
    _package("franklinwh_direct_or_cloud", Client=type("Client", (), {}))

if _missing("httpx"):
    _module("httpx", AsyncClient=type("AsyncClient", (), {}))

if _missing("probatio"):
    _module("probatio")


# --- homeassistant stubs -----------------------------------------------------

if _missing("homeassistant"):

    class HomeAssistant:
        """Minimal hass with a recording event bus."""

        def __init__(self) -> None:
            self.bus = MagicMock()
            self.data: dict[str, Any] = {}

    def callback(func: Any) -> Any:
        return func

    class Event:
        def __init__(self, event_type: str, data: dict[str, Any]) -> None:
            self.event_type = event_type
            self.data = data

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    class ConfigEntryNotReady(HomeAssistantError):
        pass

    class UpdateFailed(HomeAssistantError):
        pass

    class DataUpdateCoordinator[T]:
        """Just enough of the real coordinator for _async_update_data tests."""

        def __init__(
            self,
            hass: HomeAssistant,
            logger: logging.Logger,
            *,
            name: str,
            update_interval: timedelta | None = None,
            always_update: bool = True,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.always_update = always_update
            self.data: T | None = None
            self.last_update_success = True
            self.last_update_success_time: datetime | None = None
            self.last_exception: Exception | None = None

        def __class_getitem__(cls, item: Any) -> Any:
            return cls

        async def _async_update_data(self) -> T:
            raise NotImplementedError

        async def async_refresh(self) -> None:
            try:
                self.data = await self._async_update_data()
            except Exception as err:  # noqa: BLE001
                self.last_exception = err
                self.last_update_success = False
            else:
                self.last_update_success = True
                self.last_update_success_time = datetime.now(UTC)

        async def async_config_entry_first_refresh(self) -> None:
            self.data = await self._async_update_data()
            self.last_update_success = True

        async def async_request_refresh(self) -> None:
            await self.async_refresh()

    class CoordinatorEntity:
        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator

        def __class_getitem__(cls, item: Any) -> Any:
            return cls

    class DeviceInfo(dict):
        pass

    class ConfigEntry:
        def __init__(self, data: dict[str, Any] | None = None) -> None:
            self.data = data or {}
            self.options: dict[str, Any] = {}
            self.entry_id = "entry"
            self.title = "FranklinWH"

    _now = datetime(2026, 11, 11, 21, 0, tzinfo=UTC)

    def utcnow() -> datetime:
        return _now

    def get_default_time_zone() -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo("UTC")

    def get_time_zone(name: str) -> zoneinfo.ZoneInfo | None:
        try:
            return zoneinfo.ZoneInfo(name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            return None

    async def async_get_time_zone(name: str) -> zoneinfo.ZoneInfo | None:
        return get_time_zone(name)

    _package("homeassistant")
    _module(
        "homeassistant.core",
        HomeAssistant=HomeAssistant,
        callback=callback,
        Event=Event,
    )
    _module(
        "homeassistant.exceptions",
        HomeAssistantError=HomeAssistantError,
        ConfigEntryAuthFailed=ConfigEntryAuthFailed,
        ConfigEntryNotReady=ConfigEntryNotReady,
    )
    _module("homeassistant.config_entries", ConfigEntry=ConfigEntry)
    _package("homeassistant.helpers")
    _module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        UpdateFailed=UpdateFailed,
        CoordinatorEntity=CoordinatorEntity,
    )
    _module("homeassistant.helpers.device_registry", DeviceInfo=DeviceInfo)
    _module(
        "homeassistant.helpers.httpx_client",
        SSL_ALPN_HTTP11_HTTP2="h2",
        create_async_httpx_client=lambda *a, **k: None,
    )

    # entity platforms (sensor.py, binary_sensor.py, event.py)

    class EntityCategory(str, Enum):
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    class SensorDeviceClass(str, Enum):
        BATTERY = "battery"
        DATE = "date"
        ENERGY = "energy"
        ENERGY_STORAGE = "energy_storage"
        ENUM = "enum"
        POWER = "power"
        TEMPERATURE = "temperature"
        TIMESTAMP = "timestamp"

    class SensorStateClass(str, Enum):
        MEASUREMENT = "measurement"
        TOTAL = "total"
        TOTAL_INCREASING = "total_increasing"

    class BinarySensorDeviceClass(str, Enum):
        CONNECTIVITY = "connectivity"
        POWER = "power"
        PROBLEM = "problem"

    class UnitOfEnergy(str, Enum):
        KILO_WATT_HOUR = "kWh"

    class UnitOfPower(str, Enum):
        WATT = "W"
        KILO_WATT = "kW"

    class UnitOfTemperature(str, Enum):
        CELSIUS = "°C"

    @dataclass(frozen=True, kw_only=True)
    class EntityDescription:
        """Mirror of the EntityDescription fields the integration sets."""

        key: str
        device_class: Any = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True
        icon: str | None = None
        name: Any = None
        translation_key: str | None = None
        unit_of_measurement: str | None = None

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription(EntityDescription):
        native_unit_of_measurement: str | None = None
        options: list[str] | None = None
        state_class: Any = None
        suggested_display_precision: int | None = None

    @dataclass(frozen=True, kw_only=True)
    class BinarySensorEntityDescription(EntityDescription):
        pass

    class Entity:
        _attr_translation_key: str | None = None
        _attr_unique_id: str | None = None

        @property
        def unique_id(self) -> str | None:
            return self._attr_unique_id

        def async_write_ha_state(self) -> None:
            pass

    class SensorEntity(Entity):
        pass

    class BinarySensorEntity(Entity):
        pass

    class EventEntity(Entity):
        """Records the last triggered event like the real EventEntity."""

        _attr_event_types: ClassVar[list[str]] = []

        @property
        def event_types(self) -> list[str]:
            return self._attr_event_types

        def _trigger_event(
            self, event_type: str, event_attributes: dict[str, Any] | None = None
        ) -> None:
            if event_type not in self._attr_event_types:
                raise ValueError(f"Invalid event type {event_type}")
            self.last_event_type = event_type
            self.last_event_attributes = event_attributes

    _module(
        "homeassistant.const",
        PERCENTAGE="%",
        CONF_PASSWORD="password",
        CONF_USERNAME="username",
        EntityCategory=EntityCategory,
        UnitOfEnergy=UnitOfEnergy,
        UnitOfPower=UnitOfPower,
        UnitOfTemperature=UnitOfTemperature,
    )
    _package("homeassistant.components")
    _module(
        "homeassistant.components.sensor",
        SensorDeviceClass=SensorDeviceClass,
        SensorEntity=SensorEntity,
        SensorEntityDescription=SensorEntityDescription,
        SensorStateClass=SensorStateClass,
    )
    _module(
        "homeassistant.components.binary_sensor",
        BinarySensorDeviceClass=BinarySensorDeviceClass,
        BinarySensorEntity=BinarySensorEntity,
        BinarySensorEntityDescription=BinarySensorEntityDescription,
    )
    _module("homeassistant.components.event", EventEntity=EventEntity)
    _module("homeassistant.helpers.entity_platform", AddConfigEntryEntitiesCallback=Any)
    _package("homeassistant.util")
    _module(
        "homeassistant.util.dt",
        utcnow=utcnow,
        get_default_time_zone=get_default_time_zone,
        get_time_zone=get_time_zone,
        async_get_time_zone=async_get_time_zone,
    )


# --- synthetic integration package ------------------------------------------

if "franklin_wh" not in sys.modules:
    package = types.ModuleType("franklin_wh")
    package.__path__ = [str(REPO_ROOT)]
    package.__spec__ = ModuleSpec("franklin_wh", None, is_package=True)
    package.__spec__.submodule_search_locations = [str(REPO_ROOT)]
    sys.modules["franklin_wh"] = package


# --- fixtures ----------------------------------------------------------------

# imported after the stubs are registered
from franklin_wh import coordinator as coordinator_module  # noqa: E402
from franklin_wh.coordinator import FranklinWHCoordinator  # noqa: E402
from franklin_wh.data import MessageStats  # noqa: E402
from franklinwh import ExportMode, ExportSettings  # noqa: E402

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402


def load_fixture(name: str) -> Any:
    """Load a JSON fixture by file name."""
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def run(coro: Any) -> Any:
    """Run a coroutine to completion on a fresh event loop."""
    return asyncio.run(coro)


GATEWAY_ID = "10060010A01X00000001"
T0 = datetime(2026, 11, 11, 21, 0, tzinfo=UTC)


class Clock:
    """Controllable replacement for dt_util.utcnow."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeClient:
    """Fake franklinwh client: composite results are consumed from a queue."""

    def __init__(self) -> None:
        self.gateway = GATEWAY_ID
        self.url_base = "https://example.invalid/"
        self.composite_queue: list[Any] = []
        self.composite_calls = 0
        self.get_calls: list[str] = []
        self.fail_paths: set[str] = set()
        self.gateway_list_error: Exception | None = None
        self.tou_error: Exception | None = None
        self.messages: list[Any] = load_fixture("messages.json")
        self.messages_error: Exception | None = None
        self.messages_calls: list[int] = []
        self.unread = 0

    async def get_stats(self) -> dict[str, Any]:
        return {"stats": True}

    async def get_message_stats(self) -> MessageStats:
        return MessageStats(unread=self.unread)

    async def get_mode(self) -> dict[str, Any]:
        return {"mode": 2}

    async def get_composite_info(self) -> dict[str, Any]:
        self.composite_calls += 1
        item = self.composite_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get_export_settings(self) -> ExportSettings:
        return ExportSettings(mode=ExportMode.SOLAR_AND_APOWER, limit_kw=None)

    async def get_home_gateway_list(self) -> list[dict[str, Any]]:
        if self.gateway_list_error:
            raise self.gateway_list_error
        return load_fixture("gateway_list.json")

    async def get_tou_settings(self) -> dict[str, Any]:
        if self.tou_error:
            raise self.tou_error
        return load_fixture("tou.json")

    async def get_messages(self, count: int = 1, page: int = 1) -> list[dict]:
        self.messages_calls.append(count)
        if self.messages_error:
            raise self.messages_error
        return copy.deepcopy(self.messages[:count])

    async def _get(self, url: str, params: dict | None = None) -> dict[str, Any]:
        path = url.removeprefix(self.url_base)
        self.get_calls.append(path)
        if path in self.fail_paths:
            return {"code": 500, "message": "boom"}
        match path:
            case "hes-gateway/terminal/obtainApowersInfo":
                return {"code": 200, "result": load_fixture("apowers.json")}
            case "hes-gateway/terminal/v2/warrantyInfo":
                return {"code": 200, "result": load_fixture("warranty.json")}
            case "hes-gateway/terminal/getGatewaySystemSetting":
                return {"code": 200, "result": load_fixture("system_setting.json")}
        raise AssertionError(f"unexpected GET {path}")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(dt_util, "utcnow", clock)
    return clock


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def coordinator(
    monkeypatch: pytest.MonkeyPatch, client: FakeClient, clock: Clock
) -> FranklinWHCoordinator:
    async def fake_get_client(*args: Any, **kwargs: Any) -> tuple[None, FakeClient]:
        return None, client

    monkeypatch.setattr(coordinator_module, "get_client", fake_get_client)
    return FranklinWHCoordinator(
        hass=HomeAssistant(),
        username="user",
        password="pass",
        gateway_id=GATEWAY_ID,
    )


@pytest.fixture
def composite() -> dict[str, Any]:
    """Captured getDeviceCompositeInfo result (scrubbed)."""
    return load_fixture("composite.json")


@pytest.fixture
def apowers() -> list[dict[str, Any]]:
    """Captured obtainApowersInfo result (scrubbed)."""
    return load_fixture("apowers.json")


@pytest.fixture
def warranty() -> dict[str, Any]:
    """Captured v2/warrantyInfo result (scrubbed)."""
    return load_fixture("warranty.json")


@pytest.fixture
def system_setting() -> dict[str, Any]:
    """Captured getGatewaySystemSetting result (scrubbed)."""
    return load_fixture("system_setting.json")


@pytest.fixture
def gateway_list() -> list[dict[str, Any]]:
    """Captured getHomeGatewayList result (scrubbed)."""
    return load_fixture("gateway_list.json")


@pytest.fixture
def messages() -> list[dict[str, Any]]:
    """Captured selectTerPushMessageListApp result (scrubbed)."""
    return load_fixture("messages.json")


@pytest.fixture
def tou() -> dict[str, Any]:
    """Captured get_tou_settings result."""
    return load_fixture("tou.json")


@pytest.fixture
def tz() -> zoneinfo.ZoneInfo:
    """The gateway's zone."""
    return zoneinfo.ZoneInfo("America/Los_Angeles")
