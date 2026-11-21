"""Constants for the Dura-i integration."""

from homeassistant.const import Platform

DOMAIN = "dura_i"
INVERTER_POLL_INTERVAL_SECONDS = 10

# Modbus link tuning. The RS485 bus is potentially shared, so a request now and then
# collides and gets no answer. pymodbus's own 3 retries made that worse: the
# adapter answered every copy and the burst of late replies desynced the
# connection ("request ask for transaction_id=N but got id=N-1"). Instead we
# wait longer, let pymodbus try once, and make one retry of our own on the same
# connection. Only a run of unanswered requests forces a reconnect, so a
# collision costs one late reading rather than a reconnect and a gap in data.
MODBUS_TIMEOUT_SECONDS = 5
MODBUS_READ_ATTEMPTS = 2
MODBUS_FAILURES_BEFORE_RECONNECT = 3
# Large blocks are split into reads of at most this many registers; the
# inverter is markedly slower answering a single 64-register read.
MODBUS_MAX_REGISTERS_PER_READ = 32
# Pause between requests so the bus is quiet before the next one goes out.
MODBUS_REQUEST_GAP_SECONDS = 0.1
IMPORT_EXPORT_MONITOR_DURATION_SECONDS = 120
IMPORT_EXPORT_THRESHOLD = 0.1
MODBUS_MAX_SLAVE_ADDRESS = 1  # Stops us wasting time because the Dura-i doesn't let you change the slave address on parallel systems.
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]
