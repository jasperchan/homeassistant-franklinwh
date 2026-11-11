"""Diagnostics support for FranklinWH."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .alarms import alarm_attributes
from .const import CONF_GATEWAY_ID, DOMAIN
from .coordinator import FranklinWHCoordinator
from .messages import diagnostics_messages
from .raw import jsonable

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_GATEWAY_ID,
    "token",
    "access_token",
    "gatewayId",
    "alarmEqSn",
    "fhpSn",
    "apowerSn",
    "sn",
    "account",
    "installerCompany",
    "installerCompanyPhone",
    "installerCompanyEmail",
    "equipmentSupplierPhone",
    "zipCode",
    "address",
    "firstName",
    "lastName",
    "equipment",
    "equipment_sn",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators: dict[str, FranklinWHCoordinator] = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(entry.data, TO_REDACT),
        },
        "gateways": {
            gateway_id[-6:]: _gateway_diagnostics(coordinator)
            for gateway_id, coordinator in coordinators.items()
        },
    }


def _gateway_diagnostics(coordinator: FranklinWHCoordinator) -> dict[str, Any]:
    """Get diagnostics for one gateway coordinator."""
    diagnostics: dict[str, Any] = {
        "direct_connect": bool(coordinator.direct_host),
        "last_update_success": coordinator.last_update_success,
        "last_update_time": coordinator.last_update_success_time.isoformat()
        if coordinator.last_update_success_time
        else None,
        "update_interval": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
    }
    data = coordinator.data
    if data is None:
        diagnostics["error"] = "No data available"
        return diagnostics

    if data.stats:
        try:
            stats = data.stats
            diagnostics["stats"] = {
                "current": {
                    "battery_soc": getattr(stats.current, "battery_soc", None),
                    "battery_use": getattr(stats.current, "battery_use", None),
                    "home_load": getattr(stats.current, "home_load", None),
                    "grid_use": getattr(stats.current, "grid_use", None),
                    "solar_production": getattr(
                        stats.current, "solar_production", None
                    ),
                    "generator_production": getattr(
                        stats.current, "generator_production", None
                    ),
                    "switch_1_load": getattr(stats.current, "switch_1_load", None),
                    "switch_2_load": getattr(stats.current, "switch_2_load", None),
                    "v2l_use": getattr(stats.current, "v2l_use", None),
                },
                "totals": {
                    "battery_charge": getattr(stats.totals, "battery_charge", None),
                    "battery_discharge": getattr(
                        stats.totals, "battery_discharge", None
                    ),
                    "grid_import": getattr(stats.totals, "grid_import", None),
                    "grid_export": getattr(stats.totals, "grid_export", None),
                    "solar": getattr(stats.totals, "solar", None),
                    "generator": getattr(stats.totals, "generator", None),
                    "switch_1_use": getattr(stats.totals, "switch_1_use", None),
                    "switch_2_use": getattr(stats.totals, "switch_2_use", None),
                    "v2l_export": getattr(stats.totals, "v2l_export", None),
                    "v2l_import": getattr(stats.totals, "v2l_import", None),
                },
            }
        except Exception as err:  # noqa: BLE001
            diagnostics["stats_error"] = str(err)

    diagnostics["composite"] = (
        async_redact_data(data.composite, TO_REDACT) if data.composite else None
    )

    if (slow := data.slow) is not None:
        gateway = dict(slow.gateway) if slow.gateway else None
        if gateway:
            gateway.pop("id", None)
        diagnostics["slow"] = async_redact_data(
            {
                "apowers": slow.apowers,
                "warranty": slow.warranty,
                "system_setting": slow.system_setting,
                "export": {
                    "mode": slow.export.mode.name,
                    "limit_kw": slow.export.limit_kw,
                }
                if slow.export
                else None,
                "gateway": gateway,
                "tou": slow.tou,
                "updated_at": slow.updated_at.isoformat() if slow.updated_at else None,
                "fetched_at": jsonable(slow.fetched_at),
            },
            TO_REDACT,
        )

    diagnostics["composite_fetched_at"] = (
        data.composite_fetched_at.isoformat() if data.composite_fetched_at else None
    )
    if (message_list := data.message_list) is not None:
        # titles and metadata only: message bodies can quote account details
        diagnostics["messages"] = {
            "fetched_at": message_list.fetched_at.isoformat(),
            "items": diagnostics_messages(message_list.items),
        }

    diagnostics["alarms"] = async_redact_data(
        [alarm_attributes(alarm) for alarm in data.alarms], TO_REDACT
    )
    diagnostics["alarm_history"] = async_redact_data(
        [
            {
                "action": transition.action,
                "at": transition.at.isoformat(),
                **alarm_attributes(transition.alarm),
            }
            for transition in coordinator.alarm_history
        ],
        TO_REDACT,
    )
    return diagnostics
