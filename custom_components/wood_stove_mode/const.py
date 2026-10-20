"""Constants for the Wood Stove Mode integration."""

DOMAIN = "wood_stove_mode"

# Config keys
CONF_STOVE_SENSORS = "stove_sensors"
CONF_EXCHANGER_SENSORS = "exchanger_sensors"
CONF_WATER_SENSOR = "water_sensor"
CONF_SAT_ENTITY = "sat_entity"
CONF_NEST_ENTITY = "nest_entity"
CONF_NEST_SETPOINT = "nest_setpoint"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_ROOMS = "rooms"

# Per room keys
CONF_ROOM_NAME = "name"
CONF_ROOM_CLIMATE = "climate"
CONF_ROOM_OPENING = "opening_entity"
CONF_ROOM_INHIBIT = "inhibit_entity"
CONF_ROOM_DUMP = "dump"

# Thresholds and timing
CONF_STOVE_START_TEMP = "stove_start_temp"
CONF_EXIT_TEMP = "exit_temp"
CONF_MIN_WOOD_MINUTES = "min_wood_minutes"
CONF_REENTRY_MINUTES = "reentry_minutes"
CONF_BAND_LOW = "band_low"
CONF_BAND_HIGH = "band_high"
CONF_BAND_AIM = "band_aim"
CONF_WATER_TARGET = "water_target"
CONF_UPDATE_SECONDS = "update_seconds"
CONF_START_OPENING = "start_opening"
CONF_EMERGENCY_TEMP = "emergency_temp"
CONF_SENSOR_DIFF = "sensor_diff"
CONF_STALE_MINUTES = "stale_minutes"
CONF_PID_KP = "pid_kp"
CONF_PID_KI = "pid_ki"
CONF_PID_KD = "pid_kd"
CONF_RELEASE_TIMEOUT = "release_timeout"

# Notification toggles
CONF_NOTIFY_MODE = "notify_mode"
CONF_NOTIFY_EMERGENCY = "notify_emergency"
CONF_NOTIFY_NEST = "notify_nest"

DEFAULTS = {
    CONF_NEST_SETPOINT: 15.0,
    CONF_STOVE_START_TEMP: 60.0,
    CONF_EXIT_TEMP: 45.0,
    CONF_MIN_WOOD_MINUTES: 30,
    CONF_REENTRY_MINUTES: 10,
    CONF_BAND_LOW: 60.0,
    CONF_BAND_HIGH: 70.0,
    CONF_BAND_AIM: 65.0,
    CONF_WATER_TARGET: 55.0,
    CONF_UPDATE_SECONDS: 120,
    CONF_START_OPENING: 25,
    CONF_EMERGENCY_TEMP: 85.0,
    CONF_SENSOR_DIFF: 5.0,
    CONF_STALE_MINUTES: 5,
    CONF_PID_KP: 4.0,
    CONF_PID_KI: 0.01,
    CONF_PID_KD: 0.0,
    CONF_RELEASE_TIMEOUT: 30,
    CONF_NOTIFY_MODE: True,
    CONF_NOTIFY_EMERGENCY: True,
    CONF_NOTIFY_NEST: True,
}

# How often the controller looks at the sensors, in seconds. This is not the valve
# update interval: valves change at most once per CONF_UPDATE_SECONDS.
TICK_SECONDS = 15

STORAGE_VERSION = 1
