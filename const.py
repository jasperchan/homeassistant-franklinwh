"""Constants for the FranklinWH integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "franklin_wh"

# Configuration
CONF_GATEWAY_ID: Final = "gateway_id"
CONF_SCAN_LOCAL_NETWORKS: Final = "scan_local_networks"

# Default values
DEFAULT_NAME: Final = "FranklinWH"
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds
DEFAULT_LOCAL_SCAN_INTERVAL: Final = 10  # seconds for local API

# API endpoints (for local API when available)
LOCAL_API_PORT: Final = 8080
LOCAL_API_TIMEOUT: Final = 10

# Device info
MANUFACTURER: Final = "FranklinWH"
MODEL: Final = "aPower/aGate Energy Storage System"

# Composite info (getDeviceCompositeInfo) polling: the cloud answers
# {"code": 429} when polled too often, so never fetch it more than once per
# COMPOSITE_MIN_INTERVAL and tolerate a few failures before dropping the data.
COMPOSITE_MIN_INTERVAL: Final = timedelta(seconds=60)
# A poll that lands this close to the gate counts as due: the coordinator's
# own schedule is COMPOSITE_MIN_INTERVAL in cloud mode, so without slack the
# gate would sit exactly on the scheduling boundary and skip whole cycles.
COMPOSITE_GATE_TOLERANCE: Final = timedelta(seconds=5)
COMPOSITE_MAX_FAILURES: Final = 3

# Slow group (aPower info, warranty, system settings, export settings, gateway)
SLOW_UPDATE_INTERVAL: Final = timedelta(minutes=60)
SLOW_RETRY_INTERVAL: Final = timedelta(minutes=5)
# Failed members are retried every SLOW_RETRY_INTERVAL at most this many times
# in a row; after that the group falls back to the hourly cadence.
SLOW_MAX_RETRIES: Final = 3

# Alarms
EVENT_ALARM: Final = "franklin_wh_alarm"
ALARM_HISTORY_SIZE: Final = 50
ATTR_ALARMS: Final = "alarms"

# Push messages (selectTerPushMessageListApp). Messages arrive rarely (about
# one a day in captures) and the per-poll unread count already flags a new
# one, so the list is refreshed every MESSAGES_UPDATE_INTERVAL or as soon as
# the unread count changes; that keeps cloud traffic flat even in Direct
# Connect mode where the coordinator polls every 10 s.
EVENT_MESSAGE: Final = "franklin_wh_message"
MESSAGES_UPDATE_INTERVAL: Final = timedelta(minutes=5)
MESSAGE_LIST_SIZE: Final = 20
MESSAGE_TITLE_MAX: Final = 255  # an HA state is at most 255 characters
MESSAGE_CONTENT_MAX: Final = 500
MESSAGE_KNOWN_IDS_MAX: Final = 1000
ATTR_MESSAGES: Final = "messages"
ATTR_FETCHED_AT: Final = "fetched_at"

# The recorder drops the attributes of a state whose attribute JSON exceeds
# 16384 bytes; raw payload entities are kept below this with headroom.
ATTR_MAX_BYTES: Final = 16000

# Attributes
ATTR_GATEWAY_ID: Final = "gateway_id"
ATTR_BATTERY_SOC: Final = "battery_soc"
ATTR_BATTERY_USE: Final = "battery_use"
ATTR_HOME_LOAD: Final = "home_load"
ATTR_GRID_USE: Final = "grid_use"
ATTR_SOLAR_PRODUCTION: Final = "solar_production"
ATTR_GENERATOR_PRODUCTION: Final = "generator_production"

# Services
SERVICE_SET_OPERATION_MODE: Final = "set_operation_mode"
SERVICE_SET_BATTERY_RESERVE: Final = "set_battery_reserve"
SERVICE_GET_MESSAGES: Final = "get_messages"

# Operation modes
MODE_SELF_USE: Final = "self_use"
MODE_BACKUP: Final = "backup"
MODE_TIME_OF_USE: Final = "time_of_use"
MODE_CLEAN_BACKUP: Final = "clean_backup"

OPERATION_MODES: Final = [
    MODE_SELF_USE,
    MODE_BACKUP,
    MODE_TIME_OF_USE,
    MODE_CLEAN_BACKUP,
]
