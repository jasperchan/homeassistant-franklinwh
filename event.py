"""Event platform for FranklinWH integration.

The ``alarm`` event entity records every alarm raised/cleared transition and
the ``message`` event entity every new push message the coordinator detects,
so the recorder/logbook keep the history the FranklinWH homeowner API does
not provide. Both listen on the Home Assistant event bus (``EVENT_ALARM`` /
``EVENT_MESSAGE``) filtered by gateway id.
"""

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alarms import EVENT_TYPES as ALARM_EVENT_TYPES
from .const import DOMAIN, EVENT_ALARM, EVENT_MESSAGE
from .coordinator import FranklinWHCoordinator
from .messages import EVENT_TYPES as MESSAGE_EVENT_TYPES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FranklinWH event entities."""
    coordinators: dict[str, FranklinWHCoordinator] = hass.data[DOMAIN][entry.entry_id]

    for subentry_id, sub in entry.subentries.items():
        assert sub.unique_id is not None
        coordinator = coordinators[sub.unique_id]
        async_add_entities(
            [
                FranklinWHAlarmEventEntity(coordinator, entry),
                FranklinWHMessageEventEntity(coordinator, entry),
            ],
            config_subentry_id=subentry_id,
        )


class FranklinWHBusEventEntity(CoordinatorEntity[FranklinWHCoordinator], EventEntity):
    """Event entity fed by one bus event type, filtered on this gateway."""

    _attr_has_entity_name = True
    _bus_event: str
    _source: str  # coordinator.get_source() name gating availability

    def __init__(self, coordinator: FranklinWHCoordinator, entry: ConfigEntry) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator)
        self._gateway_id = coordinator.gateway_id
        self._attr_unique_id = f"{self._gateway_id}_{self._attr_translation_key}"
        self._attr_device_info = coordinator.device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Listen for this gateway's events on the event bus."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(self._bus_event, self._on_bus_event)
        )

    @callback
    def _on_bus_event(self, event: Event) -> None:
        """Record an event of this gateway."""
        data = event.data
        if data.get("gateway_id") != self._gateway_id:
            return
        event_type, attributes = self._decode(data)
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()

    def _decode(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Return the event type and attributes for a bus payload."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.get_source(self._source) is not None
        )


class FranklinWHAlarmEventEntity(FranklinWHBusEventEntity):
    """Alarm raised/cleared transitions of one gateway."""

    _attr_translation_key = "alarm"
    _attr_event_types = ALARM_EVENT_TYPES
    _bus_event = EVENT_ALARM
    _source = "composite"

    def _decode(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """``action`` is the event type; ``time`` becomes ``since``."""
        attributes = {
            ("since" if key == "time" else key): value
            for key, value in data.items()
            if key not in ("gateway_id", "action")
        }
        return data["action"], attributes


class FranklinWHMessageEventEntity(FranklinWHBusEventEntity):
    """Push messages received for one gateway."""

    _attr_translation_key = "message"
    _attr_event_types = MESSAGE_EVENT_TYPES
    _bus_event = EVENT_MESSAGE
    _source = "message_list"

    def _decode(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Every message is ``received``; attributes are the message dict."""
        attributes = {k: v for k, v in data.items() if k != "gateway_id"}
        return MESSAGE_EVENT_TYPES[0], attributes
