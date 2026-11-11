"""Tests for the composite / slow-group value functions against the captures."""

import copy
from datetime import date

from franklin_wh import composite as values
from franklinwh import ExportMode, ExportSettings
import pytest


def test_composite_sensor_values(composite):
    assert values.ambient_temperature(composite) == 18.2
    assert values.apower_soc(composite) == 9.5
    assert values.mppt_power(composite) == 0
    assert values.pcs_state(composite) == "online"
    assert values.bms_state(composite) == "standby"
    assert values.device_status(composite) == "online"
    assert values.connection_type(composite) == "wifi"
    assert values.wifi_signal(composite) == 100
    assert values.cellular_signal(composite) == 45
    assert values.battery_charge_from_solar_today(composite) == 0.0
    assert values.solar_to_grid_today(composite) == 0.0
    assert values.battery_to_grid_today(composite) == 0.0


def test_composite_attributes(composite):
    assert values.per_apower(composite, "fhpSoc") is None  # single pack
    assert values.per_mppt(composite) == [0]
    assert values.off_grid_flag(composite) == 0
    assert values.mppt_status(composite) == [5]


def test_multi_apower(composite):
    composite = copy.deepcopy(composite)
    runtime = composite["runtimeData"]
    runtime["fhpSn"] = ["A", "B"]
    runtime["fhpSoc"] = [10.0, 20.0]
    assert values.apower_soc(composite) == 15.0
    assert values.per_apower(composite, "fhpSoc") == {"A": 10.0, "B": 20.0}
    runtime["pe_stat"] = [8, 3]
    runtime["bms_work"] = [5, 42]
    assert values.pcs_state(composite) == "online"
    assert values.per_apower_pcs_state(composite) == {"A": "online", "B": "fault"}
    assert values.per_apower_bms_state(composite) == {"A": "standby", "B": None}


def test_single_apower_has_no_per_apower_states(composite):
    assert values.per_apower_pcs_state(composite) is None
    assert values.per_apower_bms_state(composite) is None


def test_composite_binary_values(composite):
    assert values.grid_connected(composite) is True
    assert values.mppt_locked(composite) is True


def test_off_grid(composite):
    composite = copy.deepcopy(composite)
    composite["runtimeData"]["elecnet_state"] = 1
    composite["runtimeData"]["mpptSta"] = [0]
    assert values.grid_connected(composite) is False
    assert values.mppt_locked(composite) is False


def test_unknown_enum_codes(composite):
    composite = copy.deepcopy(composite)
    composite["runtimeData"]["pe_stat"] = [99]
    composite["deviceStatus"] = 7
    assert values.pcs_state(composite) is None
    assert values.device_status(composite) is None


def test_missing_fields_raise_for_entity_guard(composite):
    # entities translate KeyError/IndexError into None + debug log
    composite = copy.deepcopy(composite)
    composite["runtimeData"]["pe_stat"] = []
    with pytest.raises(IndexError):
        values.pcs_state(composite)
    del composite["runtimeData"]["t_amb"]
    with pytest.raises(KeyError):
        values.ambient_temperature(composite)


def test_warranty_values(warranty):
    assert values.warranty_throughput_remaining(warranty) == 59967.82
    assert values.warranty_total_throughput(warranty) == 60000
    assert values.warranty_expiration(warranty) == date(2038, 11, 9)
    assert values.warranty_devices(warranty) == [
        {
            "model": "aGate",
            "expiration": "2038-11-09",
            "sub_module_expiration": "2031-11-09",
        },
        {
            "model": "aPower S",
            "expiration": "2041-11-09",
            "sub_module_expiration": None,
        },
    ]


def test_apower_values(apowers):
    assert values.apower_remaining_energy(apowers) == 1.4
    assert values.apower_remaining_per(apowers) is None
    two = [*apowers, {**apowers[0], "apowerSn": "X", "remainingPower": 2.1}]
    assert values.apower_remaining_energy(two) == 3.5
    assert values.apower_remaining_per(two) == {
        "10050019A00X00000001": 1.4,
        "X": 2.1,
    }


def test_export_values():
    export = ExportSettings(mode=ExportMode.SOLAR_AND_APOWER, limit_kw=None)
    assert values.export_mode(export) == "solar_and_apower"
    assert values.export_limit_kw(export) is None
    assert values.export_mode(ExportSettings(mode=ExportMode.NO_EXPORT)) == "no_export"
    assert (
        values.export_mode(ExportSettings(mode=ExportMode.SOLAR_ONLY)) == "solar_only"
    )


def test_system_setting_values(system_setting):
    assert values.grid_export_enabled(system_setting) is False
    assert values.rapid_shutdown_enabled(system_setting) is True
