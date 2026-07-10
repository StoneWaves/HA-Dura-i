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
- **Battery Load** - Battery charge/discharge power (kW, positive = charging)
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
- **Battery Temperature** - Battery temperature (°C)

### Grid Sensors
- **Grid Voltage** - Grid voltage (V)
- **Grid Current** - Grid/CT current (A)

### MPPT Sensors
- **MPPT1/2 Voltage** - String voltage (V)
- **MPPT1/2 Current** - String current (A)

### Temperature
- **Inverter Temp** - Inverter temperature (°C)

### Binary Sensors
- **Am Exporting** - Sustained grid export detected
- **Am Importing** - Sustained grid import detected

## Controllable Parameters

- **Battery Discharge Max Power** (W) - register 8474
- **Grid Charge Max Power** (W) - register 8470
- **Battery Max Charge Power** (W) - register 8472
- **Grid Feed In Max Power** (W) - register 8485
- **Charge End SoC** (%) - register 8473
- **Excess Target SoC** (%) - software-controlled

## Feed In Excess Solar Mode

The "Match Feed In To Excess Solar" switch attempts to automatically adjust grid feed-in power based on average excess solar production. This compensates for SoC to maintain a target battery level.

Parameters can be configured via integration options or the `dura_i.set_excess_params` service.

## Register Map Reference

The Duracell Dura-i uses the following key Modbus holding registers:

| Register | Description | Type | Scale |
|----------|-------------|------|-------|
| 4097 | Grid Voltage | uint16 | ×0.1 V |
| 4100 | PV Power Total | uint16 | ×0.1 W |
| 4112-4119 | MPPT1/2 Voltage, Current, Power | uint16 | various |
| 4124 | Inverter Temperature | uint16 | °C |
| 4130 | Energy Total | uint16 | kWh |
| 4136 | Energy Today | uint16 | ×0.001 kWh |
| 2041 | Grid Power | int16 | ×0.01 W |
| 2046 | Load Power | int16 | ×0.01 W |
| 4894 | Grid/CT Current | int16 | ×0.01 A |
| 8192 | Battery SOC | uint16 | % |
| 8198 | Battery Voltage | uint16 | ×0.1 V |
| 8200 | Battery Current | int16 | ×0.01 A |
| 8202 | Battery Power | int16 | ×0.1 W |
| 8219 | Battery Temperature | uint16 | °C |
| 8470 | Grid Charge Max Power | uint16 | W |
| 8472 | Max Charge Power | uint16 | W |
| 8473 | Charge End SOC | uint16 | % |
| 8474 | Max Discharge Power | uint16 | W |
| 8475 | Discharge End SOC | uint16 | % |
| 8485 | Max Grid Input | uint16 | W |

## Known Limitations

- The integration polls every 10 seconds.
- The Dura-i may not expose a work mode selection register via Modbus (unlike the CYG Skyline). If you discover the correct register, you can re-enable the select entity.
- Some register addresses may vary between firmware versions. If a sensor shows incorrect values, you may need to adjust the register offsets in `const.py`.

## Troubleshooting

If the integration fails to connect:
1. Verify your Waveshare adapter is reachable (ping its IP)
2. Confirm it's set to port 502, baud 9600, Modbus TCP to RTU
3. Check you're using pins 7 and 9 on the inverter's RS485 connector
4. Try restarting the inverter and adapter

## Credits

Based on the original [HA-Skyline](https://github.com/iPeel/HA-Skyline) integration by @iPeel.
Register mapping based on community research from the [Home Assistant forums](https://community.home-assistant.io/t/help-mapping-modbus-registers-for-dura-inverter-with-home-assistant/989077).
