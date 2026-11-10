"""Sensor platform for FranklinWH integration."""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace

from franklinwh import AccessoryType, RunStatus, Stats

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import FranklinWHCoordinator


@dataclass(frozen=True)
class FranklinWHSensorEntityDescription(SensorEntityDescription):
    """Describes FranklinWH sensor entity."""

    value_fn: Callable[[Stats], float | int | None] | None = None


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
