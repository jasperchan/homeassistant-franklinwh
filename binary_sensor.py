"""Binary sensor platform for FranklinWH integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import composite as values
from .const import DOMAIN
from .coordinator import FranklinWHCoordinator


@dataclass(frozen=True, kw_only=True)
class FranklinWHBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a FranklinWH binary sensor.

    ``source`` is ``composite``, ``slow`` or ``alarms``; for ``slow`` the
    ``slow_field`` names the FranklinWHSlowData attribute passed to ``value_fn``.
    """

    value_fn: Callable[[Any], bool | None]
    source: str = "composite"
    slow_field: str | None = None
    attributes_fn: Callable[[Any], dict[str, Any] | None] | None = None


BINARY_SENSORS: tuple[FranklinWHBinarySensorEntityDescription, ...] = (
    FranklinWHBinarySensorEntityDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        source="alarms",
        value_fn=lambda alarms: len(alarms) > 0,
    ),
    FranklinWHBinarySensorEntityDescription(
        key="grid_connected",
        translation_key="grid_connected",
        # POWER: "on" = utility power present, like core powerwall's grid status
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=values.grid_connected,
        attributes_fn=lambda c: {"off_grid_flag": values.off_grid_flag(c)},
    ),
    FranklinWHBinarySensorEntityDescription(
        key="mppt_locked",
        translation_key="mppt_locked",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # best-effort: mpptSta 5 observed only together with alarm 5144 (arc
        # lock) and zero PV at midday; the normal value is unknown, so the
        # entity is opt-in until a healthy capture confirms the mapping (the
        # raw list is always available in the mppt_status attribute)
        entity_registry_enabled_default=False,
        value_fn=values.mppt_locked,
        attributes_fn=lambda c: {"mppt_status": values.mppt_status(c)},
    ),
    FranklinWHBinarySensorEntityDescription(
        key="grid_export_enabled",
        translation_key="grid_export_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="system_setting",
        # system-level permission; differs from export_mode (TOU power control)
        value_fn=values.grid_export_enabled,
    ),
    FranklinWHBinarySensorEntityDescription(
        key="rapid_shutdown_enabled",
        translation_key="rapid_shutdown_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        source="slow",
        slow_field="system_setting",
        value_fn=values.rapid_shutdown_enabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FranklinWH binary sensors."""
    coordinators: dict[str, FranklinWHCoordinator] = hass.data[DOMAIN][entry.entry_id]

    for subentry_id, sub in entry.subentries.items():
        assert sub.unique_id is not None
        coordinator = coordinators[sub.unique_id]
        async_add_entities(
            [
                FranklinWHBinarySensorEntity(coordinator, description, entry)
                for description in BINARY_SENSORS
            ],
            config_subentry_id=subentry_id,
        )


class FranklinWHBinarySensorEntity(
    CoordinatorEntity[FranklinWHCoordinator], BinarySensorEntity
):
    """Representation of a FranklinWH binary sensor."""

    entity_description: FranklinWHBinarySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        description: FranklinWHBinarySensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gateway_id}_{description.key}"
        self._attr_device_info = coordinator.device_info(entry)

    @property
    def _source(self) -> Any:
        """The payload this sensor reads from, ``None`` when unavailable."""
        description = self.entity_description
        return self.coordinator.get_source(description.source, description.slow_field)

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (source := self._source) is None:
            return None
        try:
            return self.entity_description.value_fn(source)
        except (AttributeError, TypeError, KeyError, IndexError, ValueError) as err:
            self.coordinator.logger.debug(
                "Error getting value for %s: %s", self.entity_description.key, err
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes derived from the same payload."""
        attributes_fn = self.entity_description.attributes_fn
        if attributes_fn is None or (source := self._source) is None:
            return None
        try:
            return attributes_fn(source)
        except (AttributeError, TypeError, KeyError, IndexError, ValueError) as err:
            self.coordinator.logger.debug(
                "Error getting attributes for %s: %s", self.entity_description.key, err
            )
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._source is not None
