# HomeAssistant Duracell Dura-i Integration

This integration communicates with your Duracell Dura-i hybrid inverter system (rebranded Hoymiles HYS series), providing real-time visibility on solar output, battery status, grid utilisation and more. It also allows you to control various charging/discharging parameters.

Based on the [CYG Skyline integration](https://github.com/iPeel/HA-Skyline) by @iPeel, adapted for the Duracell Dura-i register map.

## Supported Hardware

- Duracell Dura-i hybrid inverter (G3 and similar models)
- Duracell Dura 5 battery
- Any Hoymiles HYS series hybrid inverter with compatible firmware

## Connection Method

The integration communicates via Modbus TCP. You need an RS485 to Ethernet adapter (such as the Waveshare RS485 to Ethernet adapter) connected to the inverter's RS485 port.

### RS485 Connector

The Dura-i uses a different RS485 connector from CYG Skyline inverters. Use **pins 7 and 9** on the inverter's communication port.

## Modbus Adapter Configuration

You will need a Modbus to TCP-RTU adapter, such as the [Waveshare RS485 to Ethernet adapter](https://thepihut.com/products/rs485-to-rj45-ethernet-module).

Configure the adapter:

1. Set the device port to **502**
2. Set the baud rate to **9600**
3. Change the protocol to **Modbus TCP to RTU**

Make sure the adapter has a static IP address on your network.

## Prerequisites

This integration is managed through the Home Assistant Community Store (HACS). Follow the [HACS installation steps](https://hacs.xyz/) before continuing.

## Installation

From the HACS menu, press the three dots on the top right and select Custom Repositories. Enter the repository URL and set the category to Integration. Download the integration and restart Home Assistant if requested.

## Configuration

Once installed, add your inverter from Settings > Devices > Integrations tab. Click "Add Integration" then select "Duracell Dura-i Inverter". Enter the IP address of your Modbus adapter.

## Sensors Provided

### Power Sensors
- **PV Power** - Total solar generation (kW)
- **MPPT1/MPPT2 Power** - Individual string power (kW)
- **Battery Load** - Battery charge/discharge power (kW, negative = charging, positive = discharging)
- **Grid Load** - Grid import/export power (kW, positive = importing)
- **Current Load** - House consumption (kW)
- **Inverter Load** - Total inverter output (kW)

### Energy Sensors
- **PV Energy Today** - Solar generation today (kWh)
- **PV Energy Total** - Lifetime solar generation (kWh)

### Battery Sensors
- **State of Charge** - Battery level (%)
- **Battery Voltage** - Battery voltage (V)
- **Battery Current** - Battery current (A)

### Grid Sensors
- **Grid Voltage** - Grid voltage (V)
- **Grid Current** - Grid/CT current (A)

### MPPT Sensors
- **MPPT1/2 Voltage** - String voltage (V)
- **MPPT1/2 Current** - String current (A)

### Temperature
- **System Temp** - Inverter temperature (°C)

### Binary Sensors
- **Am Exporting** - Sustained grid export detected
- **Am Importing** - Sustained grid import detected

## Controllable Parameters

These are disabled by default so read-only users never see a control that changes the inverter. Enable the ones you want from the device page.

- **Hybrid Work Mode** - register 8448 (`0x2100`)
- **Charge Window 1 Start** / **End** (time) - registers 8450 / 8451 (`0x2102` / `0x2103`)
- **Grid Charge Max Power** (kW) - register 8470 (`0x2116`)
- **Grid Charge Max SoC** (%) - register 8471 (`0x2117`): highest SoC the battery charges to from the grid
- **Battery Max Charge Power** (kW) - register 8472 (`0x2118`)
- **Solar Charge Max SoC** (%) - register 8473 (`0x2119`): highest SoC the battery charges to from solar
- **Battery Discharge Max Power** (kW) - register 8474 (`0x211A`)
- **EPS Enabled** - register 8476 (`0x211C`)
- **Force Charge** - register 8494 (`0x212E`): on writes 1 (force charge), off writes 0 (normal). Taken from the Solis register map and not yet confirmed on Dura-i hardware.
- **Grid Feed In Max Power** (kW) - register 12474 (`0x30BA`)

## Register Map Reference

Every register the integration reads, with its address, data type and scale, is defined in [`registers.py`](custom_components/dura_i/registers.py). That file is the source of truth for what the code does. [`solis_dura_i_modbus_register_map.md`](solis_dura_i_modbus_register_map.md) is the wider reference used when looking for new registers.

To expose another register, add it to `REGISTERS` in `registers.py` (growing its block in `BLOCKS` if needed), then add an entity for it in the matching platform file, e.g. a row in `INVERTER_SENSORS` in `sensor.py`.

## Known Limitations

- The integration polls every 10 seconds.
- On some Dura-i firmware, changing the work mode over Modbus may be restricted.
- Some register addresses may vary between firmware versions. If a sensor shows incorrect values, check its entry in `registers.py`.

## Troubleshooting

If the integration fails to connect:
1. Verify your Waveshare adapter is reachable (ping its IP)
2. Confirm it's set to port 502, baud 9600, Modbus TCP to RTU
3. Check you're using pins 7 and 9 on the inverter's RS485 connector
4. Try restarting the inverter and adapter

## Credits

Based on the original [HA-Skyline](https://github.com/iPeel/HA-Skyline) integration by @iPeel.
Register mapping based on community research from the [Home Assistant forums](https://community.home-assistant.io/t/help-mapping-modbus-registers-for-dura-inverter-with-home-assistant/989077).
