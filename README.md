# HomeAssistant Duracell Dura-i Integration

This integration communicates with your Duracell Dura-i hybrid inverter system (rebranded Hoymiles HYS series), providing real-time visibility on solar output, battery status, grid utilisation and more. It also allows you to control various charging/discharging parameters.

Based on the [CYG Skyline integration](https://github.com/iPeel/HA-Skyline) by @iPeel, adapted for the Duracell Dura-i register map.

## Supported Hardware

- Duracell Dura-i hybrid inverter (G3 and similar models)
- Duracell Dura5 and Dura16 batteries
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
- **EPS Load** - Backup (EPS) output power (kW)
- **Dura-i Consumer Load** - EPS plus grid-tied load across all inverters (kW, disabled by default)

On systems with more than one inverter, system-wide **Dura-i PV Power**, **Battery Load**, **Grid Load**, **Current Load**, **EPS Load** and **Inverter Load** sensors sum all the inverters.

### Energy Sensors
- **PV Energy Today / Total** - Solar generation (kWh)
- **Grid Energy In / Out Today** and **Total** - Grid import and export (kWh)
- **Battery Energy In / Out Today** and **Total** - Battery charge and discharge (kWh)

The "Today" sensors reset at midnight. The "Total" sensors are lifetime counters that ignore any drop of more than 1 kWh, so a bad read can't put a spike in the energy dashboard.

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

### Settings and Diagnostics (read-only, disabled by default)
These show inverter settings and battery detail without letting you change them. Everything below except the firmware versions comes from the Solis register map and is **not yet confirmed** on Dura-i hardware.

- **Version Master / Slave / EMS** - Firmware versions
- **Charge Window 1 Current Limit** (A) - register 8452 (`0x2104`), 0 = no limit
- **Discharge Window 1 Current Limit** (A) - register 8455 (`0x2107`), 0 = no limit
- **Battery Reserve SoC** (%) - register 8475 (`0x211B`)
- **Max Depth of Discharge** (%) - register 8493 (`0x212D`)
- **Max Charge Limit Power** (kW) - register 8485 (`0x2125`). Reads 9 kW, above the inverter's own limit, so its meaning is doubtful.
- **Register 8505 (Unidentified)** - register 8505 (`0x2139`), meaning unknown
- **Inverter Clock** - input registers 3021–3026
- **Battery State of Health** (%) and **Max / Min Cell Voltage** (V) - input registers 33140–33142

The clock and battery values use input registers. If the inverter doesn't answer them, they stay unknown and are retried every 10 minutes.

## Controllable Parameters

These are disabled by default so read-only users never see a control that changes the inverter. Enable the ones you want from the device page.

- **Hybrid Work Mode** - register 8448 (`0x2100`)
- **Charge Window 1 Start** / **End** (time) - registers 8450 / 8451 (`0x2102` / `0x2103`)
- **Discharge Window 1 Start** / **End** (time) - registers 8453 / 8454 (`0x2105` / `0x2106`). Taken from the Solis register map and not yet confirmed on Dura-i hardware.
- **Grid Charge Max Power** (kW) - register 8470 (`0x2116`)
- **Grid Charge Max SoC** (%) - register 8471 (`0x2117`): highest SoC the battery charges to from the grid
- **Battery Max Charge Power** (kW) - register 8472 (`0x2118`)
- **Solar Charge Max SoC** (%) - register 8473 (`0x2119`): highest SoC the battery charges to from solar
- **Battery Discharge Max Power** (kW) - register 8474 (`0x211A`)
- **EPS Enabled** - register 8476 (`0x211C`)
- **Force Charge** - register 8494 (`0x212E`): on writes 1 (force charge), off writes 0 (normal). Taken from the Solis register map and not yet confirmed on Dura-i hardware.
- **Force Charge Target SoC** (%) - register 8504 (`0x2138`): the SoC a force charge stops at. Taken from the Solis register map and not yet confirmed on Dura-i hardware.
- **Grid Feed In Max Power** (kW) - register 12474 (`0x30BA`)

The power controls' maximums follow your inverter model, from the Dura-i G3 datasheet:

| Model | Battery charge/discharge, grid charge | Grid feed-in |
|-------|------------------------------|--------------|
| PD-DH1P-3.6K-G3 | 4.0 kW | 3.6 kW |
| PD-DH1P-4.6K-G3 | 5.5 kW | 4.6 kW |
| PD-DH1P-5K-G3 | 5.5 kW | 5.0 kW |
| PD-DH1P-6K-G3 | 6.6 kW | 6.0 kW |

Unrecognised models get the 3.6 kW limits to be safe, and a warning is logged so the model can be added. On parallel systems each maximum is multiplied by the number of inverters. Your battery may set a lower limit, which the inverter enforces itself; for example a single Dura5 is about 5.1 kW.

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
