# FranklinWH Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-blue.svg?style=for-the-badge)](https://github.com/hacs/integration)

This is a modern custom integration for [Home Assistant](https://www.home-assistant.io/) that provides comprehensive monitoring and control for FranklinWH home energy storage systems.

> ⚠️ This project is unofficial and not affiliated with FranklinWH.

______________________________________________________________________

## 📝 About This Fork

Based on complete rewrite by Joshua Seidel ([@JoshuaSeidel](https://github.com/JoshuaSeidel)) with Anthropic Claude Sonnet 4.5.\
Originally inspired by [@richo](https://github.com/richo)'s [homeassistant-franklinwh](https://github.com/richo/homeassistant-franklinwh).\
[Extended](https://github.com/jkt628/homeassistant-franklinwh) by [@jkt628](https://github.com/jkt628) with support for
multiple installations, Direct Connect, and new controls for Mode, Reserve, SmartCircuits, _etc._\
Uses [@jkt628](https://github.com/jkt628)'s fork of [franklinwh-python](https://github.com/jkt628/franklinwh-python) library.

______________________________________________________________________

## ✨ Features

### Accessories

Additional sensors and controls become available depending on an installation's accessories and configuration.

- ⚡ [Generator Module](https://www.franklinwh.com/accessories/generator-module/) production and energy insights
- 🎛️ [Smart Circuits Module](https://www.franklinwh.com/accessories/smart-circuits/) monitoring and control

### Monitoring

- 📊 Live battery status (State of Charge, charging/discharging power)
- ☀️ Solar production and energy generation tracking
- 🔌 Grid import/export monitoring with totals
- 🏠 Home load power monitoring and total energy consumption

### Control

- ⚙️ Operation mode selection (self_use, backup, time_of_use)
- 🔋 Battery reserve setting
- 🌐 Grid connection control

### Modern Features

- 🎨 **Config Flow**: Easy setup through the Home Assistant UI
- 🏘️ **Multiple Installation**: Individual controls for each FranklinWH installation
- 🔄 **DataUpdateCoordinator**: Efficient polling with minimal API calls
- 📱 **Device Registry**: All entities grouped under one device per installation
- 🔍 **Diagnostics**: Built-in debugging support
- 🌐 **Direct Connect Support**: most-used statistics do not rely on cloud (beta)
- 🛠️ **Services**: Custom services for advanced control

______________________________________________________________________

## 📦 Installation

### Via HACS (Recommended)

1. In Home Assistant, go to **HACS → Integrations**.
1. Click the menu (⋮) → **Custom repositories**.
1. Add this repository URL: <https://github.com/jkt628/homeassistant-franklinwh>
1. Choose category **Integration** and click **Add**.
1. Search for **FranklinWH** in HACS and click **Download**.
1. Restart Home Assistant.

### Manual Installation

1. Download this repository as a ZIP file.
1. Extract the contents to your Home Assistant `custom_components/franklin_wh/` directory.
1. Restart Home Assistant.

______________________________________________________________________

## ⚙️ Configuration

### Easy Setup (Config Flow - Recommended)

1. Go to **Settings → Devices & Services**.

1. Click **+ Add Integration**.

1. Search for **FranklinWH**.

1. Enter your credentials:

   - **Email Address**: Your FranklinWH account email
   - **Password**: Your FranklinWH account password

1. Click **Submit** and your devices will be added automatically!

______________________________________________________________________

## 📊 Available Entities

After setup, all entities will be organized under a single **FranklinWH** device per installation:

### Sensors (some depend on installation accessories and configuration)

| Entity | Description | Unit |
| --- | --- | --- |
| **State of Charge** | Battery state of charge | % |
| **Battery Use** | Battery charging/discharging rate (negative = charging) | kW |
| **Battery Charge** | Total energy charged to battery | kWh |
| **Battery Discharge** | Total energy discharged from battery | kWh |
| **Battery Charge from Grid** | Energy charged to battery from grid (calculated) | kWh |
| **Home Load** | Instantaneous home power consumption | kW |
| **Grid Use** | Net grid power (negative = importing, positive = exporting) | kW |
| **Grid Import** | Total energy imported from grid | kWh |
| **Grid Export** | Total energy exported to grid | kWh |
| **Solar Production** | Instantaneous solar power generation | kW |
| **Solar Energy** | Total solar energy produced | kWh |
| **Home Energy Total** | Total energy consumed by home | kWh |
| **Run Status** | Battery operating status | Standby, Charging, Discharging |
| **Generator Use** | Generator power output (live) | kW |
| **Generator Energy** | Total generator energy produced | kWh |
| **Circuits 1 Use** | Power draw on Switch 1 | kW |
| **Circuits 1 Lifetime Use** | Total energy used by Switch 1 | kWh |
| **Circuits 2 Use** | Power draw on Switch 2 | kW |
| **Circuits 2 Lifetime Use** | Total energy used by Switch 2 | kWh |
| **Circuits 3 Use** | Power draw on Switch 3 | kW |
| **Circuits 3 Import** | Total energy drawn from Circuits 3 | kWh |
| **Circuits 3 Export** | Total energy delivered to Circuits 3 | kWh |
| **Unread Messages** | Count of unread messages | count |

### Diagnostics and alarms

Read from the cloud composite status (once per minute) and a slow group of
settings refreshed hourly. Diagnostic entities are listed under the device's
**Diagnostic** section; the rest are operational.

| Entity | Platform | Description | Unit |
| --- | --- | --- | --- |
| **Problem** | binary_sensor | On while any alarm is active | |
| **Grid connected** | binary_sensor | On while utility power is present (`elecnet_state`); attribute `off_grid_flag` | |
| **MPPT locked** | binary_sensor | On when an aPower MPPT reports status 5 (best-effort: seen with the arc-lock alarm; disabled by default until the healthy value is confirmed, raw list in attribute `mppt_status`) | |
| **Grid export enabled** | binary_sensor | System-level grid export permission (installer setting) | |
| **Rapid shutdown enabled** | binary_sensor | PV rapid shutdown enabled | |
| **Alarm** | event | `raised` / `cleared` transitions with code, name, level, since, equipment, explanation and fix plan; an alarm is the same alarm while its code and equipment serial match, whatever `id` the cloud re-logs it under; the recorder keeps the alarm history | |
| **Active alarms** | sensor | Number of active alarms; attribute `alarms` lists them | count |
| **Ambient temperature** | sensor | Gateway ambient temperature | °C |
| **Battery pack SOC** | sensor | Raw aPower pack SOC (mean over packs; attribute `per_apower`) | % |
| **MPPT power** | sensor | DC PV power through the aPower MPPTs (attribute `per_mppt`); unit unverified (all captures read 0), disabled by default until it is confirmed against Solar Production | W |
| **PCS state** | sensor | Power electronics state (attribute `per_apower`) | enum |
| **BMS state** | sensor | Battery management state (attribute `per_apower`) | enum |
| **Device status** | sensor | Standby / charging / discharging / fault / offline | enum |
| **Connection type** | sensor | Ethernet / Wi-Fi / cellular | enum |
| **Wi-Fi signal** | sensor | Wi-Fi signal strength | % |
| **Cellular signal** | sensor | Cellular signal strength (vendor scale) | |
| **Battery charge from solar today** | sensor | Daily bucket, resets at local midnight | kWh |
| **Solar export to grid today** | sensor | Daily bucket | kWh |
| **Battery export to grid today** | sensor | Daily bucket | kWh |
| **Warranty throughput remaining** | sensor | Remaining warranty throughput allowance (attribute `total_throughput`) | kWh |
| **Warranty expiration** | sensor | System warranty expiration (attribute `devices`) | date |
| **Battery remaining energy** | sensor | Remaining energy reported per aPower, summed; refreshed hourly | kWh |
| **Export mode** | sensor | No export / solar only / solar and aPower | enum |
| **Message** | event | `received` for every new push message (title, content, type, received time); the recorder keeps the message history | |
| **Latest message** | sensor | Title of the newest push message; attributes carry its `id`, `type`, `sub_type`, `content`, `received`, `read` and `messages`, the last 20 messages | |

The device's firmware (`sw_version`) and hardware (`hw_version`) versions are
filled in from the gateway list.

#### Raw payloads

These diagnostic sensors expose the cloud replies verbatim as attributes (no
field renaming, so undecoded fields are visible and queryable from the
recorder history). Every attribute set carries `fetched_at` (UTC) and stays
under the recorder's 16 KB attribute limit; with the captured payloads the
largest, the runtime data, is about 1.5 KB. The runtime data changes every
poll, so expect roughly 2 MB of recorder history per day from it.

| Entity | State | Attributes | Refresh |
| --- | --- | --- | --- |
| **Raw runtime data** | mode name | `getDeviceCompositeInfo` `runtimeData` | per poll (≥ 60 s) |
| **Raw composite status** | decoded `deviceStatus` | the composite minus `runtimeData` and `currentAlarmVOList` (`currentWorkMode`, `deviceStatus`, `solarHaveVo`, `valid`, `csipAuxGatewayOnline`) | per poll |
| **Raw alarms** | alarm count | `currentAlarmVOList` verbatim | per poll |
| **Raw aPower info** | aPower count | `obtainApowersInfo` list under `result` (firmware versions, ratings, remaining energy, SOC) | hourly |
| **Raw system settings** | fetch time | `getGatewaySystemSetting` | hourly |
| **Raw warranty info** | expiration date | `v2/warrantyInfo` | hourly |
| **Raw gateway info** | firmware version | the `getHomeGatewayList` entry of this gateway | hourly |
| **Raw export settings** | export mode | `mode` and `limit_kw` from `get_export_settings` | hourly |
| **Raw TOU settings** | current mode name | `get_tou_settings` (`getGatewayTouListV2`) | hourly |

#### Alarm code catalog

`alarm_codes.py` maps all 477 known alarm codes to their English names (from
`selectDeviceRunLogList`) and fills in the name of an alarm the cloud reports
without one. Regenerate it from a fresh capture with
`python3 -I tools/gen_alarm_codes.py <capture.json>`.

#### `franklin_wh_alarm` bus event

Every alarm transition also fires a `franklin_wh_alarm` event on the Home
Assistant event bus (the first poll after startup seeds the active alarms
silently, so a restart does not replay long-standing alarms):

```yaml
event_type: franklin_wh_alarm
data:
  gateway_id: "10060010A01X00000001"
  action: raised            # or cleared
  id: 2756389132
  code: "5144"
  common_code: "5#44"
  name: "NO.1 MPPT The arc lock fault occurs"
  level: 2
  time: "2026-11-10T15:01:30-08:00"
  equipment_sn: "10050019A00X00000001"
  explanation: "The arcing fault of the PV branch x has been triggered multiple times ..."
  plan: "1、Check all connection points ...\n2、...\n3、..."
```

Use it as an `event` trigger, or trigger on the `event.*_alarm` entity's state
changes.

#### `franklin_wh_message` bus event

Every new push message (the list is refreshed every 5 minutes, or at once when
the unread count changes; the first list after startup is seeded silently)
fires a `franklin_wh_message` event with the same attributes the `Message`
event entity records:

```yaml
event_type: franklin_wh_message
data:
  gateway_id: "10060010A01X00000001"
  id: 6569334
  title: "4G signal is poor"
  type: 1
  sub_type: 1
  content: "4G Poor signal. Perform network detection or connect to Ethernet or Wifi."
  received: "2026-11-10T18:49:31-08:00"
  read: false
```

### Controls (some depend on installation accessories and configuration)

| Entity | Description |
| --- | --- |
| **Backup Reserve** | Configure minimum Backup Reserve percentage for current Operating Mode |
| **Operating Mode** | Time of Use (TOU), Self-Consumption, Emergency Backup, [VPP](https://www.franklinwh.com/support/overview/virtual-power-plant) |
| **Grid Connection** | Monitor and control grid connection status |
| **Generator** | Import from Generator Module |
| **Circuits 1** | Control smart circuit 1 |
| **Circuits 2** | Control smart circuit 2 |
| **Circuits 3** | Control smart circuit 3 |

______________________________________________________________________

## 🔧 Services

The integration provides custom services for advanced control:

### `franklin_wh.get_messages

Get last messages

**Parameters:**

- `count`: Number of messages to retrieve (1-10)

**Example:**

```yaml
service: franklin_wh.get_messages
data:
  count: 1
```

### `franklin_wh.set_operation_mode`

Set the operation mode of your FranklinWH system.

> [!WARNING]
> Deprecated in favor of `Operating Mode` control.

**Parameters:**

- `mode`: Operation mode (`self_use`, `backup`, `time_of_use`, `clean_backup`)

**Example:**

```yaml
service: franklin_wh.set_operation_mode
data:
  mode: self_use
```

### `franklin_wh.set_battery_reserve`

Set the minimum battery reserve percentage.

> [!WARNING]
> Deprecated in favor of `Backup Reserve` control.

**Parameters:**

- `reserve_percent`: Minimum battery charge to maintain (0-100)

**Example:**

```yaml
service: franklin_wh.set_battery_reserve
data:
  reserve_percent: 20
```

______________________________________________________________________

## Action to retrieve latest unread messages

```yaml
alias: FranklinWH unread -> notification
description: 'Notify latest unread messages'
triggers:
  - trigger: state
    entity_id:
      - sensor.franklinwh_unread_messages
conditions:
  - condition: numeric_state
    entity_id: sensor.franklinwh_unread_messages
    above: 0
actions:
  - sequence:
      - action: franklin_wh.get_messages
        metadata: {}
        data:
          count: >-
            {{ clamp(states("sensor.franklinwh_unread_messages") | int, 1, 10) }}
        response_variable: unread
      - action: persistent_notification.create
        metadata: {}
        data:
          title: FranklinWH Unread
          message: >-
            {{ unread.messages | join("<br>") }}
mode: single
```

______________________________________________________________________

## 🔋 Energy Dashboard Integration

All energy sensors are compatible with Home Assistant's **Energy Dashboard**:

1. Go to **Settings → Dashboards → Energy**
1. Configure your energy sources:
   - **Solar Production**: Use "Solar Energy" sensor
   - **Battery**: Use "Battery Charge" and "Battery Discharge" sensors
   - **Battery from Grid**: Use "Battery Charge from Grid" sensor (calculated)
   - **Grid**: Use "Grid Import" and "Grid Export" sensors

______________________________________________________________________

## 🐛 Troubleshooting

### No entities appear after setup

1. Check **Settings → System → Logs** for errors containing `franklin_wh`
1. Verify your credentials are correct
1. Ensure FranklinWH cloud services are online

### Authentication errors

1. Try re-authenticating:
   - Go to **Settings → Devices & Services**
   - Find your FranklinWH integration
   - Click **Configure** → **Re-authenticate**
1. Verify your password is correct

### Entities show as "Unavailable"

1. Check your internet connection
1. Verify the FranklinWH cloud service is accessible
1. Check the integration logs for API errors
1. Try reloading the integration

### Gateway Timeout Errors

If you see "Device response timed out":

1. **Verify gateway is online**: Check the FranklinWH mobile app
1. **Check Gateway ID**: Must be exact SN from app (More → Site Address → SN)
1. **FranklinWH cloud status**: Service may be temporarily down
1. **Wait and retry**: Gateway may be rebooting or updating

### Direct Connect Issues

Direct Connect is **beta** and may not work:

- Most users should use **cloud polling** (default)
- Direct Connect requires the gateway to support local communication
- If Direct Connect times out, clear the Option value to use cloud polling
- Direct Connect support depends on gateway firmware version

### Diagnostics

To get detailed diagnostic information:

1. Go to **Settings → Devices & Services**
1. Find your FranklinWH integration
1. Click the device, then click **Download Diagnostics**
1. Attach the diagnostics file when reporting issues

______________________________________________________________________

## 🔍 Direct Connect Support (Beta)

This integration includes beta support for Direct Connect communication which bypasses cloud for most-used statistics.

**To enable Direct Connect:**

1. Open Options for the integration
1. Scan local networks or enter your gateway's IPv4 address
1. The integration will attempt Direct Connect with faster polling (10 seconds vs 60 seconds)

**To disable Direct Connect:**

1. Open Options for the integration
1. Clear the IPv4 address to enable cloud polling

______________________________________________________________________

## 🤝 Contributing

Contributions are welcome! Please fork the repository and open a pull request:

👉 [https://github.com/jkt628/homeassistant-franklinwh](https://github.com/jkt628/homeassistant-franklinwh)

### Development Setup

1. Clone the repository
1. Install development dependencies
1. Use [VS Code with Dev Containers](https://github.com/jkt628/homeassistant-franklinwh-dev) for a consistent environment
1. Test your changes thoroughly before submitting

### Reporting Issues

When reporting issues, please:

1. Download diagnostics from your integration
1. Include Home Assistant and integration versions
1. Provide relevant log entries
1. Describe steps to reproduce

______________________________________________________________________

## 📋 Changelog

### Version 2026.11.12 (current)

- 🐛 **FIX**: alarms are identified by code and equipment serial, not by the
  cloud `id`. The aPower re-logs an active alarm under a fresh `id` (and
  sometimes a fresh `time`) whenever it re-evaluates it, which made the `alarm`
  event fire a raised/cleared pair for an alarm that never went away; a re-log
  now keeps the earliest `since` and the latest record's `id`

### Version 2026.11.11

- ✨ **NEW**: diagnostics and alarms: `problem`, `grid_connected`, `mppt_locked`,
  `grid_export_enabled`, `rapid_shutdown_enabled` binary sensors, an `alarm` event
  entity plus the `franklin_wh_alarm` bus event, composite-info sensors (ambient
  temperature, pack SOC, MPPT power, PCS/BMS/device/connection states, signal
  strengths, daily solar/battery export buckets) and hourly warranty / export mode /
  remaining energy sensors
- ✨ **NEW**: push messages as content: `latest_message` sensor (last 20 messages
  as attributes), `message` event entity and the `franklin_wh_message` bus event
- ✨ **NEW**: raw payload sensors (`raw_runtime`, `raw_composite_misc`, `raw_alarms`,
  `raw_apowers`, `raw_system_setting`, `raw_warranty`, `raw_gateway`,
  `raw_export_settings`, `raw_tou`) exposing the cloud replies verbatim as
  attributes, plus the alarm code catalog (`alarm_codes.py`)
- 🔧 Diagnostics download now covers every gateway with composite, slow-group,
  message (titles only) and alarm history data (serials and installer contact
  redacted)

### Version 2026.10.4

- ✨ **NEW**: Direct Connect with scanning local networks using
  [@david2069](https://github.com/david2069)'s
  [franklinwh-direct-connect-api](https://github.com/david2069/franklinwh-direct-connect-api)

### Version 2026.9.0

- ⬆️ **UPGRADED**: Updated to [@jkt628](https://github.com/jkt628)'s fork of franklinwh library 2026.9.0
- ✨ **NEW**: support multiple installation with accessories
- ✨ **NEW**: Operating Mode monitoring and control
- ✨ **NEW**: Backup Reserve monitoring and control
- ✨ **NEW**: Generator monitoring and control
- 🐛 **FIXED**: Smart Circuits switch controls
- 📝 **DOCS**: Updated README to reflect available features

### Version 1.1.0

- ⬆️ **UPGRADED**: Updated to franklinwh library 1.0.0
- ✨ **NEW**: Full operation mode control (self_use, backup, time_of_use)
- ✨ **NEW**: Battery reserve percentage setting
- ✨ **NEW**: Grid connection switch for monitoring and control
- ✨ **NEW**: Home Energy Total sensor (total home consumption)
- 🐛 **FIXED**: Integration now properly works with franklinwh 1.0.0 API
- ♻️ **IMPROVED**: Updated imports to use properly exported classes
- 📝 **DOCS**: Updated README to reflect available features

### Version 1.0.9

- ⬆️ **UPGRADED**: Updated to franklinwh library 1.0.0
- ✨ **NEW**: Full operation mode control (self_use, backup, time_of_use)
- ✨ **NEW**: Battery reserve percentage setting
- ✨ **NEW**: Grid connection switch for monitoring and control
- ✨ **NEW**: Home Energy Total sensor (total home consumption)
- 🐛 **FIXED**: Integration now properly works with franklinwh 1.0.0 API
- ♻️ **IMPROVED**: Updated imports to use properly exported classes
- 📝 **DOCS**: Updated README to reflect available features

### Version 1.0.7

- 🐛 **CRITICAL FIX**: Removed Grid Connection switch (requires unreleased library version)
- 🐛 **FIXED**: ImportError for AccessoryType and GridStatus classes
- 🐛 **FIXED**: Integration now loads successfully with franklinwh 0.4.1
- ℹ️ **NOTE**: Smart circuit switches (1-3) still work correctly

### Version 1.0.6

- 🐛 **CRITICAL FIX**: Fixed Stats class import from franklinwh.client module
- 🐛 **FIXED**: "cannot import name 'Stats'" ImportError on setup

### Version 1.0.5

- 🐛 **CRITICAL FIX**: Corrected franklinwh package requirement to 0.4.1 (was incorrectly set to 0.5.0 which doesn't exist)
- 🐛 **FIXED**: "Requirements for franklin_wh not found" error on setup

### Version 1.0.4

- ✨ **NEW**: Battery Charge from Grid calculated sensor
- 🐛 **FIXED**: Entities no longer flicker unavailable during temporary failures
- 🐛 **FIXED**: Energy Dashboard compatibility (all sensors in kWh)
- ♻️ **IMPROVED**: Resilient coordinator with 3-failure grace period
- ♻️ **IMPROVED**: Better error logging and failure tracking
- ⚠️ **NOTE**: Grid Connection switch from this version removed in 1.0.7 (library compatibility)

### Version 1.0.0-1.0.3

- ✨ **NEW**: Modern config flow for UI-based setup
- ✨ **NEW**: DataUpdateCoordinator for efficient API polling
- ✨ **NEW**: Device registry integration
- ✨ **NEW**: Diagnostics support
- ✨ **NEW**: Experimental local API support
- ✨ **NEW**: Custom services (placeholders for future features)
- 🐛 **FIXED**: All typos and copy-paste errors in entity IDs
- 🐛 **FIXED**: Consolidated caching logic
- 🐛 **FIXED**: Improved error handling
- ♻️ **REFACTOR**: Complete code modernization
- ♻️ **REFACTOR**: Better entity organization

### Version 0.4.1 (Legacy)

- Initial YAML-based platform configuration by @richo
- Basic sensor and switch support

______________________________________________________________________

## 📄 License

This project is dual-licensed under:

- **MIT License**
- **Apache License 2.0**

You may choose either license when using or contributing to this project.

______________________________________________________________________

## 🙏 Acknowledgments

- **Original Integration**: [@richo](https://github.com/richo) for the initial implementation
- **Python Library**: [`franklinwh-python`](https://github.com/richo/franklinwh-python) by @richo
- **Rewrite**: Joshua Seidel with Anthropic Claude Sonnet 4.5
- **Community**: Thanks to the Home Assistant community
- **Contributors**: Special thanks to all contributors including [@jkt628](https://github.com/jkt628) for Grid Connection switch

______________________________________________________________________

## ⚠️ Disclaimer

This integration is not affiliated with, endorsed by, or supported by FranklinWH. Use at your own risk. The developers are not responsible for any damage to your system or equipment.

______________________________________________________________________

## 🎉 **Enjoy your FranklinWH integration!**

For support, please open an issue on [GitHub](https://github.com/jkt628/homeassistant-franklinwh/issues).
