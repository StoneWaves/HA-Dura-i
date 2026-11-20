"""Constants for the Dura-i integration."""

from homeassistant.const import Platform

DOMAIN = "dura_i"
INVERTER_POLL_INTERVAL_SECONDS = 10

# Modbus link tuning. TCP-RS485 adapters on a busy bus can take well over
# pymodbus's 3s default to answer. pymodbus's own retries re-send under a new
# transaction id, so the late reply to the first send then looks stale and the
# connection desyncs ("request ask for transaction_id=N but got id=N-1").
# Instead we wait longer, let pymodbus give up after one try, and reset the
# socket before our own single retry so no late reply can be mistaken for the
# next one.
MODBUS_TIMEOUT_SECONDS = 5
MODBUS_READ_ATTEMPTS = 2
# Large blocks are split into reads of at most this many registers; the
# inverter is markedly slower answering a single 64-register read.
MODBUS_MAX_REGISTERS_PER_READ = 32
# Pause between requests so the adapter's RS485 side can settle.
MODBUS_REQUEST_GAP_SECONDS = 0.05
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
