"""Sensor platform for FranklinWH integration."""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from franklinwh import AccessoryType, RunStatus, Stats

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import composite as values, raw
from .alarms import (
    BMS_STATE,
    CONN_TYPE,
    DEVICE_STATUS,
    EXPORT_MODE,
    PCS_STATE,
    alarm_attributes,
    enum_options,
)
from .const import ATTR_ALARMS, ATTR_FETCHED_AT, DOMAIN, MANUFACTURER, MODEL
from .coordinator import FranklinWHCoordinator
from .messages import latest_attributes, latest_title


@dataclass(frozen=True)
class FranklinWHSensorEntityDescription(SensorEntityDescription):
    """Describes FranklinWH sensor entity."""

    value_fn: Callable[[Stats], float | int | None] | None = None


@dataclass(frozen=True)
class FranklinWHDataSensorEntityDescription(FranklinWHSensorEntityDescription):
    """Describes a sensor fed by the composite info, the alarms or the slow group.

    ``source`` is ``composite``, ``alarms``, ``slow`` or ``message_list``;
    for ``slow`` ``slow_field`` names the FranklinWHSlowData attribute passed
    to ``value_fn``/``attributes_fn``. ``alarms_fn`` receives the parsed
    alarms for attribute building. With ``fetched_at`` the attributes carry
    the fetch time of the source and, when ``value_fn`` is ``None``, that time
    is the state (pair it with ``SensorDeviceClass.TIMESTAMP``).
    """

    source: str = "composite"
    slow_field: str | None = None
    attributes_fn: Callable[[Any], dict[str, Any] | None] | None = None
    alarms_fn: Callable[[Any], dict[str, Any] | None] | None = None
    fetched_at: bool = False


COMPOSITE_SENSORS: tuple[FranklinWHDataSensorEntityDescription, ...] = (
    FranklinWHDataSensorEntityDescription(
        key="active_alarms",
        translation_key="active_alarms",
        entity_category=EntityCategory.DIAGNOSTIC,
        # count the parsed alarms so the state, the ``alarms`` attribute, the
        # problem binary sensor and the alarm events all agree
        source="alarms",
        value_fn=len,
        alarms_fn=lambda alarms: {ATTR_ALARMS: [alarm_attributes(a) for a in alarms]},
    ),
    FranklinWHDataSensorEntityDescription(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.ambient_temperature,
    ),
    FranklinWHDataSensorEntityDescription(
        key="apower_soc",
        translation_key="apower_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.apower_soc,
        attributes_fn=lambda c: {"per_apower": values.per_apower(c, "fhpSoc")},
    ),
    FranklinWHDataSensorEntityDescription(
        key="mppt_power",
        translation_key="mppt_power",
        # W is the working assumption (see composite.mppt_power); the unit is
        # unverified until a non-zero sample exists, so the entity stays
        # disabled by default rather than feeding long-term statistics that
        # could be off by 1000x.
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=values.mppt_power,
        attributes_fn=lambda c: {"per_mppt": values.per_mppt(c)},
    ),
    FranklinWHDataSensorEntityDescription(
        key="pcs_state",
        translation_key="pcs_state",
        device_class=SensorDeviceClass.ENUM,
        options=enum_options(PCS_STATE),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.pcs_state,
        attributes_fn=lambda c: {"per_apower": values.per_apower_pcs_state(c)},
    ),
    FranklinWHDataSensorEntityDescription(
        key="bms_state",
        translation_key="bms_state",
        device_class=SensorDeviceClass.ENUM,
        options=enum_options(BMS_STATE),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.bms_state,
        attributes_fn=lambda c: {"per_apower": values.per_apower_bms_state(c)},
    ),
    FranklinWHDataSensorEntityDescription(
        key="device_status",
        translation_key="device_status",
        device_class=SensorDeviceClass.ENUM,
        options=enum_options(DEVICE_STATUS),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.device_status,
    ),
    FranklinWHDataSensorEntityDescription(
        key="connection_type",
        translation_key="connection_type",
        device_class=SensorDeviceClass.ENUM,
        options=enum_options(CONN_TYPE),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.connection_type,
    ),
    FranklinWHDataSensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.wifi_signal,
    ),
    FranklinWHDataSensorEntityDescription(
        key="cellular_signal",
        translation_key="cellular_signal",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=values.cellular_signal,
    ),
    FranklinWHDataSensorEntityDescription(
        key="battery_charge_from_solar_today",
        translation_key="battery_charge_from_solar_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=values.battery_charge_from_solar_today,
    ),
    FranklinWHDataSensorEntityDescription(
        key="solar_to_grid_today",
        translation_key="solar_to_grid_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=values.solar_to_grid_today,
    ),
    FranklinWHDataSensorEntityDescription(
        key="battery_to_grid_today",
        translation_key="battery_to_grid_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=values.battery_to_grid_today,
    ),
)
SLOW_SENSORS: tuple[FranklinWHDataSensorEntityDescription, ...] = (
    FranklinWHDataSensorEntityDescription(
        key="warranty_throughput_remaining",
        translation_key="warranty_throughput_remaining",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="warranty",
        value_fn=values.warranty_throughput_remaining,
        attributes_fn=lambda w: {
            "total_throughput": values.warranty_total_throughput(w)
        },
    ),
    FranklinWHDataSensorEntityDescription(
        key="warranty_expiration",
        translation_key="warranty_expiration",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="warranty",
        value_fn=values.warranty_expiration,
        attributes_fn=lambda w: {"devices": values.warranty_devices(w)},
    ),
    FranklinWHDataSensorEntityDescription(
        key="apower_remaining_energy",
        translation_key="apower_remaining_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="apowers",
        value_fn=values.apower_remaining_energy,
        attributes_fn=lambda a: {"per_apower": values.apower_remaining_per(a)},
    ),
    FranklinWHDataSensorEntityDescription(
        key="export_mode",
        translation_key="export_mode",
        device_class=SensorDeviceClass.ENUM,
        options=enum_options(EXPORT_MODE),
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="export",
        value_fn=values.export_mode,
        attributes_fn=lambda e: {"limit_kw": values.export_limit_kw(e)},
    ),
)
MESSAGE_LIST_SENSORS: tuple[FranklinWHDataSensorEntityDescription, ...] = (
    FranklinWHDataSensorEntityDescription(
        key="latest_message",
        translation_key="latest_message",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="message_list",
        value_fn=latest_title,
        attributes_fn=latest_attributes,
        # no fetched_at: it would change every list refresh and make the
        # recorder store the whole message list again with nothing new
    ),
)
# Raw payloads, verbatim, so undecoded fields are visible in HA and recorded
# as history. All are well under the recorder's 16 KB attribute limit with
# the captured payloads (runtimeData, the largest, is about 1.5 KB).
RAW_SENSORS: tuple[FranklinWHDataSensorEntityDescription, ...] = (
    FranklinWHDataSensorEntityDescription(
        key="raw_runtime",
        translation_key="raw_runtime",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=raw.runtime_state,
        attributes_fn=raw.runtime,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_composite_misc",
        translation_key="raw_composite_misc",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=raw.composite_misc_state,
        attributes_fn=raw.composite_misc,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_alarms",
        translation_key="raw_alarms",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=raw.alarms_count,
        attributes_fn=raw.alarms,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_apowers",
        translation_key="raw_apowers",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="apowers",
        value_fn=raw.count,
        attributes_fn=raw.result_list,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_system_setting",
        translation_key="raw_system_setting",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="system_setting",
        attributes_fn=raw.mapping,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_warranty",
        translation_key="raw_warranty",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="warranty",
        value_fn=raw.warranty_state,
        attributes_fn=raw.mapping,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_gateway",
        translation_key="raw_gateway",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="gateway",
        value_fn=raw.gateway_state,
        attributes_fn=raw.mapping,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_export_settings",
        translation_key="raw_export_settings",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="export",
        value_fn=values.export_mode,
        attributes_fn=raw.export_settings,
        fetched_at=True,
    ),
    FranklinWHDataSensorEntityDescription(
        key="raw_tou",
        translation_key="raw_tou",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="tou",
        value_fn=raw.tou_state,
        attributes_fn=raw.mapping,
        fetched_at=True,
    ),
)


GENERIC_SENSORS: tuple[FranklinWHSensorEntityDescription, ...] = (
    FranklinWHSensorEntityDescription(
        key="battery_soc",
        name="State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.current.battery_soc,
    ),
    FranklinWHSensorEntityDescription(
        key="battery_use",
        name="Battery Use",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.current.battery_use * -1,
    ),
    FranklinWHSensorEntityDescription(
        key="battery_charge",
        name="Battery Charge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.battery_charge,
    ),
    FranklinWHSensorEntityDescription(
        key="battery_discharge",
        name="Battery Discharge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.battery_discharge,
    ),
    FranklinWHSensorEntityDescription(
        key="battery_charge_from_grid",
        name="Battery Charge from Grid",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: (
            # Battery charged from grid = Total battery charge - Solar energy
            # (assuming all solar goes to battery first, excess goes to home/grid)
            max(0, (stats.totals.battery_charge or 0) - (stats.totals.solar or 0))
        ),
    ),
    FranklinWHSensorEntityDescription(
        key="home_load",
        name="Home Load",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.current.home_load,
    ),
    FranklinWHSensorEntityDescription(
        key="home_use",
        name="Home Use",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.home_use,
    ),
    FranklinWHSensorEntityDescription(
        key="grid_use",
        name="Grid Use",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.current.grid_use * -1,
    ),
    FranklinWHSensorEntityDescription(
        key="grid_import",
        name="Grid Import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.grid_import,
    ),
    FranklinWHSensorEntityDescription(
        key="grid_export",
        name="Grid Export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.grid_export,
    ),
    FranklinWHSensorEntityDescription(
        key="solar_production",
        name="Solar Production",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.current.solar_production,
    ),
    FranklinWHSensorEntityDescription(
        key="solar_energy",
        name="Solar Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.solar,
    ),
)
MESSAGE_SENSORS: tuple[FranklinWHSensorEntityDescription, ...] = (
    FranklinWHSensorEntityDescription(
        key="unread_messages",
        name="Unread Messages",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda messages: messages.unread,
    ),
)
GENERATOR_SENSORS: tuple[FranklinWHSensorEntityDescription, ...] = (
    FranklinWHSensorEntityDescription(
        key="generator_use",
        name="Generator Use",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.current.generator_production,
    ),
    FranklinWHSensorEntityDescription(
        key="generator_energy",
        name="Generator Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.generator,
    ),
)
SMART_CIRCUITS_SENSORS: tuple[FranklinWHSensorEntityDescription, ...] = (
    FranklinWHSensorEntityDescription(
        key="switch_1_use",
        name="{name} Use",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda sc: sc.circuits[1].power,
    ),
    FranklinWHSensorEntityDescription(
        key="switch_1_lifetime_use",
        name="{name} Lifetime Use",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda sc: sc.circuits[1].export_energy,
    ),
    FranklinWHSensorEntityDescription(
        key="switch_2_use",
        name="{name} Use",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda sc: sc.circuits[2].power,
    ),
    FranklinWHSensorEntityDescription(
        key="switch_2_lifetime_use",
        name="{name} Lifetime Use",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda sc: sc.circuits[2].export_energy,
    ),
    FranklinWHSensorEntityDescription(
        key="v2l_use",
        name="{name} Use",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda sc: sc.circuits[3].power,
    ),
    FranklinWHSensorEntityDescription(
        key="v2l_export",
        name="{name} Export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda sc: sc.circuits[3].export_energy,
    ),
    FranklinWHSensorEntityDescription(
        key="v2l_import",
        name="{name} Import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda sc: sc.circuits[3].import_energy,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FranklinWH sensors."""
    coordinators: dict[str, FranklinWHCoordinator] = hass.data[DOMAIN][entry.entry_id]

    for subentry_id, sub in entry.subentries.items():
        assert sub.unique_id is not None
        coordinator = coordinators[sub.unique_id]

        def _entities(
            coordinator: FranklinWHCoordinator,
            descriptions: Iterable[FranklinWHSensorEntityDescription],
            cls: type[FranklinWHSensorEntity] = FranklinWHSensorEntity,
        ) -> Iterator[FranklinWHSensorEntity]:
            for description in descriptions:
                yield cls(coordinator, description, entry)

        entities = list(_entities(coordinator, GENERIC_SENSORS))
        entities.append(FranklinWHBatterySensorEntity(coordinator, entry))
        entities.extend(
            _entities(coordinator, MESSAGE_SENSORS, FranklinWHMessageSensorEntity)
        )

        accessories = await coordinator.client.get_accessories()
        coordinator.logger.debug("Accessories: %s", accessories)

        for accessory in accessories:
            try:
                match accessory["accessoryType"]:
                    case AccessoryType.GENERATOR_MODULE.id:
                        entities.extend(_entities(coordinator, GENERATOR_SENSORS))
                    case AccessoryType.SMART_CIRCUITS_MODULE.id:
                        coordinator.enable("smart_circuits")
                        sc = await coordinator.client.get_smart_circuits_enhanced()
                        for c in SMART_CIRCUITS_SENSORS:
                            if c.key.startswith("v2l_"):
                                c = replace(
                                    c, name=c.name.format(name=sc.circuits[3].name)
                                )
                            elif "_2_" in c.key:
                                if sc.merged:
                                    continue  # Skip second circuit sensors if merged
                                c = replace(
                                    c, name=c.name.format(name=sc.circuits[2].name)
                                )
                            elif "_1_" in c.key:
                                c = replace(
                                    c, name=c.name.format(name=sc.circuits[1].name)
                                )
                            entities.append(
                                FranklinWHCircuitSensorEntity(coordinator, c, entry)
                            )
            except KeyError as err:
                coordinator.logger.error(
                    "Expected key 'accessoryType' not found: %s", err
                )

        entities.extend(
            _entities(coordinator, COMPOSITE_SENSORS, FranklinWHDataSensorEntity)
        )
        entities.extend(
            _entities(coordinator, SLOW_SENSORS, FranklinWHDataSensorEntity)
        )
        entities.extend(
            _entities(coordinator, MESSAGE_LIST_SENSORS, FranklinWHDataSensorEntity)
        )
        entities.extend(_entities(coordinator, RAW_SENSORS, FranklinWHDataSensorEntity))

        async_add_entities(entities, config_subentry_id=subentry_id)


class FranklinWHSensorEntity(CoordinatorEntity[FranklinWHCoordinator], SensorEntity):
    """Representation of a FranklinWH sensor."""

    entity_description: FranklinWHSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        description: FranklinWHSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        gateway_id = coordinator.client.gateway

        # Set unique ID
        self._attr_unique_id = f"{gateway_id}_{description.key}"

        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, gateway_id)},
            name=f"FranklinWH {gateway_id[-6:]}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=entry.data.get("sw_version"),
        )

    @property
    def native_value(self) -> float | int | None:
        """Return the state of the sensor."""
        if (
            self.entity_description.value_fn is None
            or self.coordinator.data is None
            or self.coordinator.data.stats is None
        ):
            return None

        try:
            return self.entity_description.value_fn(self.coordinator.data.stats)
        except (AttributeError, TypeError, KeyError) as err:
            self.coordinator.logger.debug(
                "Error getting value for %s: %s", self.entity_description.key, err
            )
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.stats is not None
        )


class FranklinWHBatterySensorEntity(FranklinWHSensorEntity):
    """Representation of a FranklinWH battery run status."""

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            FranklinWHSensorEntityDescription(
                key="battery_run_status",
                name="Battery Run Status",
                device_class=SensorDeviceClass.ENUM,
                options=list(RunStatus.titles()),
                value_fn=lambda stats: stats.current.run_status.title,
            ),
            entry,
        )

    @property
    def icon(self) -> str:
        """Return the entity's icon."""
        match self.native_value:
            case RunStatus.STANDBY.title:
                return "mdi:battery"
            case RunStatus.CHARGING.title:
                return "mdi:battery-plus-variant"
            case RunStatus.DISCHARGING.title:
                return "mdi:battery-minus-variant"
            case _:
                return "mdi:battery-alert"


class FranklinWHCircuitSensorEntity(FranklinWHSensorEntity):
    """Representation of a FranklinWH smart circuit sensor."""

    @property
    def native_value(self) -> float | int | None:
        """Return the state of the sensor."""
        if (
            self.entity_description.value_fn is None
            or self.coordinator.data is None
            or self.coordinator.data.smart_circuits is None
        ):
            return None

        try:
            return self.entity_description.value_fn(
                self.coordinator.data.smart_circuits
            )
        except (AttributeError, TypeError, KeyError) as err:
            self.coordinator.logger.debug(
                "Error getting value for %s: %s", self.entity_description.key, err
            )
            return None


class FranklinWHDataSensorEntity(FranklinWHSensorEntity):
    """Sensor fed by the composite info (per poll) or the slow group (hourly)."""

    entity_description: FranklinWHDataSensorEntityDescription

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        description: FranklinWHDataSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description, entry)
        self._attr_device_info = coordinator.device_info(entry)

    @property
    def _source(self) -> Any:
        """The payload this sensor reads from, ``None`` when unavailable."""
        description = self.entity_description
        return self.coordinator.get_source(description.source, description.slow_field)

    @property
    def _fetched_at(self) -> datetime | None:
        """When the payload was fetched, ``None`` when unknown."""
        description = self.entity_description
        return self.coordinator.get_fetched_at(
            description.source, description.slow_field
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        description = self.entity_description
        if (source := self._source) is None:
            return None
        if description.value_fn is None:
            return self._fetched_at if description.fetched_at else None

        try:
            return description.value_fn(source)
        except (AttributeError, TypeError, KeyError, IndexError, ValueError) as err:
            self.coordinator.logger.debug(
                "Error getting value for %s: %s", description.key, err
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes derived from the same payload."""
        description = self.entity_description
        attributes: dict[str, Any] | None = None
        try:
            if description.alarms_fn is not None:
                alarms = self.coordinator.get_source("alarms")
                return None if alarms is None else description.alarms_fn(alarms)
            if (source := self._source) is None:
                return None
            if description.attributes_fn is not None:
                attributes = description.attributes_fn(source)
        except (AttributeError, TypeError, KeyError, IndexError, ValueError) as err:
            self.coordinator.logger.debug(
                "Error getting attributes for %s: %s", description.key, err
            )
            return None
        if description.fetched_at:
            fetched_at = self._fetched_at
            attributes = {
                **(attributes or {}),
                ATTR_FETCHED_AT: fetched_at.isoformat() if fetched_at else None,
            }
        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._source is not None


def account_device_id(entry: ConfigEntry) -> str:
    """Return the device registry identifier of the account-level device."""
    return f"account_{entry.entry_id}"


class FranklinWHMessageSensorEntity(FranklinWHSensorEntity):
    """Representation of a FranklinWH message sensor."""

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        description: FranklinWHSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description, entry)

        # Override unique ID
        self._attr_unique_id = description.key

        # Override device info: one stable account-level device per config
        # entry. ``{(DOMAIN)}`` was a bare string, which the device registry
        # never matched again, so every reload created a new empty device.
        self._attr_device_info["identifiers"] = {(DOMAIN, account_device_id(entry))}
        self._attr_device_info["name"] = "FranklinWH Account"

    @property
    def native_value(self) -> float | int | None:
        """Return the state of the sensor."""
        if (
            self.entity_description.value_fn is None
            or self.coordinator.data is None
            or self.coordinator.data.messages is None
        ):
            return None

        try:
            return self.entity_description.value_fn(self.coordinator.data.messages)
        except (AttributeError, TypeError, KeyError) as err:
            self.coordinator.logger.debug(
                "Error getting value for %s: %s", self.entity_description.key, err
            )
            return None

    @property
    def icon(self) -> str:
        """Return the entity's icon."""
        return "mdi:email-plus" if self.native_value else "mdi:email-outline"
