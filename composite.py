"""Value functions over the composite info and the slow-group payloads.

Pure Python (no Home Assistant imports) so the mappings can be unit tested
against captured JSON. ``composite`` is ``get_composite_info()``'s result;
the slow-group inputs are documented on each function.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from statistics import fmean
from typing import Any

from .alarms import (
    BMS_STATE,
    CONN_TYPE,
    DEVICE_STATUS,
    EXPORT_MODE,
    PCS_STATE,
    enum_option,
)

type Composite = Mapping[str, Any]


def _runtime(composite: Composite) -> Mapping[str, Any]:
    return composite["runtimeData"]


# Composite-fed sensors


def ambient_temperature(composite: Composite) -> float | None:
    """Ambient temperature, °C."""
    return _runtime(composite)["t_amb"]


def apower_soc(composite: Composite) -> float | None:
    """Mean raw pack SOC over all aPowers, %."""
    socs = [s for s in _runtime(composite)["fhpSoc"] if s is not None]
    return round(fmean(socs), 3) if socs else None


def per_apower(composite: Composite, field: str) -> dict[str, Any] | None:
    """Map serial to ``runtimeData[field][i]`` when more than one aPower is present."""
    runtime = _runtime(composite)
    serials = runtime.get("fhpSn") or []
    values = runtime.get(field) or []
    if len(serials) <= 1:
        return None
    return dict(zip(serials, values, strict=False))


def per_apower_state(
    composite: Composite, field: str, table: Mapping[Any, str]
) -> dict[str, str | None] | None:
    """Like ``per_apower`` with each code mapped through an enum ``table``."""
    raw = per_apower(composite, field)
    if raw is None:
        return None
    return {serial: enum_option(table, code) for serial, code in raw.items()}


def mppt_power(composite: Composite) -> float | None:
    """DC PV power through the aPower MPPTs (``mpptAllPower``).

    Unit unverified: every capture so far reads 0 (PV locked out by alarm
    5144). The cloud serialises its kW fields as floats (``p_sun`` 0.0) and
    this one as an integer like the fields documented in W (``solarPower``),
    so W is the working assumption; confirm against ``p_sun`` (same quantity
    on a DC-coupled install) with the first non-zero sample.
    """
    return _runtime(composite)["mpptAllPower"]


def per_mppt(composite: Composite) -> list[Any] | None:
    """Per-MPPT power list (``mpptActPower``), same unverified unit as above."""
    return list(_runtime(composite).get("mpptActPower") or [])


def pcs_state(composite: Composite) -> str | None:
    """PCS state of the first aPower."""
    return enum_option(PCS_STATE, _runtime(composite)["pe_stat"][0])


def per_apower_pcs_state(composite: Composite) -> dict[str, str | None] | None:
    """PCS state per aPower serial when more than one is present."""
    return per_apower_state(composite, "pe_stat", PCS_STATE)


def bms_state(composite: Composite) -> str | None:
    """BMS state of the first aPower."""
    return enum_option(BMS_STATE, _runtime(composite)["bms_work"][0])


def per_apower_bms_state(composite: Composite) -> dict[str, str | None] | None:
    """BMS state per aPower serial when more than one is present."""
    return per_apower_state(composite, "bms_work", BMS_STATE)


def device_status(composite: Composite) -> str | None:
    """Overall device status."""
    return enum_option(DEVICE_STATUS, composite["deviceStatus"])


def connection_type(composite: Composite) -> str | None:
    """Gateway uplink type."""
    return enum_option(CONN_TYPE, _runtime(composite)["connType"])


def wifi_signal(composite: Composite) -> int | None:
    """Wi-Fi signal, 0-100 %."""
    return _runtime(composite)["wifiSignal"]


def cellular_signal(composite: Composite) -> int | None:
    """Cellular signal on the vendor scale (0-52 observed)."""
    return _runtime(composite)["signal"]


def battery_charge_from_solar_today(composite: Composite) -> float | None:
    """Battery charge from solar today, kWh."""
    return _runtime(composite)["soChBat"]


def solar_to_grid_today(composite: Composite) -> float | None:
    """Solar export to grid today, kWh."""
    return _runtime(composite)["soOutGrid"]


def battery_to_grid_today(composite: Composite) -> float | None:
    """Battery export to grid today, kWh."""
    return _runtime(composite)["batOutGrid"]


# Composite-fed binary sensors


def grid_connected(composite: Composite) -> bool | None:
    """Return True when on grid (``elecnet_state == 0``)."""
    state = _runtime(composite)["elecnet_state"]
    return None if state is None else state == 0


def off_grid_flag(composite: Composite) -> Any:
    """Raw ``solarHaveVo.offGridFlag`` for cross-checking."""
    return (composite.get("solarHaveVo") or {}).get("offGridFlag")


def mppt_locked(composite: Composite) -> bool | None:
    """Return True when any MPPT reports status 5.

    Best-effort: 5 was observed only together with alarm 5144 (arc lock) and
    zero PV at midday; the normal value is unknown.
    """
    status = _runtime(composite).get("mpptSta")
    if status is None:
        return None
    return 5 in status


def mppt_status(composite: Composite) -> list[Any] | None:
    """Raw ``mpptSta`` list."""
    status = _runtime(composite).get("mpptSta")
    return None if status is None else list(status)


# Slow-group values


def warranty_throughput_remaining(warranty: Mapping[str, Any]) -> float | None:
    """Remaining warranty throughput, kWh (``v2/warrantyInfo``)."""
    return warranty["remainThroughput"]


def warranty_total_throughput(warranty: Mapping[str, Any]) -> float | None:
    """Total warranty throughput, kWh (vendor field is MWh)."""
    throughput = warranty.get("throughput")
    return None if throughput is None else throughput * 1000


def warranty_expiration(warranty: Mapping[str, Any]) -> date | None:
    """System warranty expiration date."""
    expiration = warranty.get("expirationTime")
    return date.fromisoformat(expiration) if expiration else None


def warranty_devices(warranty: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per-device expirations without serials."""
    return [
        {
            "model": device.get("model"),
            "expiration": device.get("expirationTime"),
            "sub_module_expiration": device.get("subModuleExpirationTime"),
        }
        for device in warranty.get("deviceExpirationList") or []
    ]


def apower_remaining_energy(apowers: Sequence[Mapping[str, Any]]) -> float | None:
    """Sum of ``remainingPower`` over all aPowers, kWh (``obtainApowersInfo``)."""
    values = [
        a["remainingPower"] for a in apowers if a.get("remainingPower") is not None
    ]
    return round(sum(values), 3) if values else None


def apower_remaining_per(apowers: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Map serial to ``remainingPower`` when more than one aPower is present."""
    if len(apowers) <= 1:
        return None
    return {a.get("apowerSn"): a.get("remainingPower") for a in apowers}


def export_mode(export: Any) -> str | None:
    """Option key for a ``franklinwh.ExportSettings``."""
    return enum_option(EXPORT_MODE, export.mode.name)


def export_limit_kw(export: Any) -> float | None:
    """Export power cap, kW, ``None`` when unlimited."""
    return export.limit_kw


def grid_export_enabled(system_setting: Mapping[str, Any]) -> bool | None:
    """System-level grid export permission (``getGatewaySystemSetting``)."""
    value = system_setting["gridExportEnable"]
    return None if value is None else bool(value)


def rapid_shutdown_enabled(system_setting: Mapping[str, Any]) -> bool | None:
    """PV rapid shutdown enabled (``getGatewaySystemSetting``)."""
    value = system_setting["rsdEnable"]
    return None if value is None else bool(value)
