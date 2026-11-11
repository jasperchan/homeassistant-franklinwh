"""The FranklinWH integration.

Complete rewrite by Joshua Seidel (@JoshuaSeidel) with Anthropic Claude Sonnet 4.5.
Originally inspired by @richo's homeassistant-franklinwh integration.
Uses the franklinwh-python library by @richo.
"""

import probatio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_GATEWAY_ID,
    DOMAIN,
    SERVICE_GET_MESSAGES,
    SERVICE_SET_BATTERY_RESERVE,
    SERVICE_SET_OPERATION_MODE,
)
from .coordinator import FranklinWHCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FranklinWH from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    coordinators = {}

    for sub in entry.subentries.values():
        assert sub.unique_id is not None
        gateway_id = sub.unique_id
        direct_host = entry.options.get(gateway_id)
        # Create coordinator
        coordinator = FranklinWHCoordinator(
            hass=hass,
            username=username,
            password=password,
            gateway_id=gateway_id,
            direct_host=direct_host,
        )

        # Fetch initial data
        try:
            await coordinator.async_config_entry_first_refresh()
            coordinator.logger.debug("FranklinWH initial data fetch complete")
        except ConfigEntryAuthFailed:
            coordinator.logger.exception("Authentication failed")
            raise
        except Exception as err:
            coordinator.logger.exception("Error setting up FranklinWH")
            raise ConfigEntryNotReady from err
        coordinators[gateway_id] = coordinator

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Record firmware/hardware versions once every platform has registered the
    # gateway device (entities passing sw_version=None would otherwise win).
    device_registry = dr.async_get(hass)
    for gateway_id, coordinator in coordinators.items():
        info = coordinator.device_info(entry)
        versions = {
            key: value
            for key in ("sw_version", "hw_version")
            if (value := info.get(key)) is not None
        }
        device = device_registry.async_get_device(identifiers={(DOMAIN, gateway_id)})
        if device is not None and versions:
            device_registry.async_update_device(device.id, **versions)

    # Register services
    async def handle_get_messages(call: ServiceCall) -> ServiceResponse:
        """Handle the get_messages service call."""
        count = call.data.get("count", 5)
        try:
            return {
                "messages": await coordinator.async_get_messages(count),
            }
        except Exception:
            coordinator.logger.exception("Failed to get messages")
            raise

    async def handle_set_operation_mode(call: ServiceCall) -> None:
        """Handle the set_operation_mode service call."""
        mode = call.data.get("mode")
        try:
            await coordinator.async_set_operation_mode(mode)
        except Exception:
            coordinator.logger.exception("Failed to set operation mode")
            raise

    async def handle_set_battery_reserve(call: ServiceCall) -> None:
        """Handle the set_battery_reserve service call."""
        reserve_percent = call.data.get("reserve_percent")
        try:
            await coordinator.async_set_battery_reserve(reserve_percent)
        except Exception:
            coordinator.logger.exception("Failed to set battery reserve")
            raise

    # Register services only once
    if not hass.services.has_service(DOMAIN, SERVICE_GET_MESSAGES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_MESSAGES,
            handle_get_messages,
            schema=probatio.Schema(
                {
                    probatio.Required("count"): probatio.All(
                        probatio.Coerce(int), probatio.Range(min=1, max=10)
                    )
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_OPERATION_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_OPERATION_MODE,
            handle_set_operation_mode,
            schema=probatio.Schema(
                {
                    probatio.Required("mode"): probatio.In(
                        ["self_use", "backup", "time_of_use", "clean_backup"]
                    )
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_BATTERY_RESERVE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_BATTERY_RESERVE,
            handle_set_battery_reserve,
            schema=probatio.Schema(
                {
                    probatio.Required("reserve_percent"): probatio.All(
                        probatio.Coerce(int), probatio.Range(min=0, max=100)
                    )
                }
            ),
        )

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing devices that no longer belong to a gateway or the account."""
    from .sensor import account_device_id

    known = {(DOMAIN, account_device_id(entry))}
    known.update(
        (DOMAIN, subentry.data[CONF_GATEWAY_ID])
        for subentry in entry.subentries.values()
        if subentry.subentry_type == "gateway"
    )
    return not any(identifier in known for identifier in device_entry.identifiers)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
