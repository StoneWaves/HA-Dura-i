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
These show inverter settings without letting you change them. Everything below except the firmware versions comes from the Solis register map and is **not yet confirmed** on Dura-i hardware.

- **Version Master / Slave / EMS** - Firmware versions
- **Battery Reserve SoC** (%) - register 8475 (`0x211B`). Auto Grid Charge also uses this as its reserve.
- **Max Depth of Discharge** (%) - register 8493 (`0x212D`)
- **Max Charge Limit Power** (kW) - register 8485 (`0x2125`). Reads 9 kW, above the inverter's own limit, so its meaning is doubtful.
- **Register 8505 (Unidentified)** - register 8505 (`0x2139`), meaning unknown

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
- **Auto Grid Charge**, **Keep Charge Window Set** and **Delay Grid Charge Start** (switches) - see [Auto Grid Charge](#auto-grid-charge). They write Grid Charge Max SoC and Charge Window 1 for you.

The power controls' maximums follow your inverter model, from the Dura-i G3 datasheet:

| Model | Battery charge/discharge, grid charge | Grid feed-in |
|-------|------------------------------|--------------|
| PD-DH1P-3.6K-G3 | 4.0 kW | 3.6 kW |
| PD-DH1P-4.6K-G3 | 5.5 kW | 4.6 kW |
| PD-DH1P-5K-G3 | 5.5 kW | 5.0 kW |
| PD-DH1P-6K-G3 | 6.6 kW | 6.0 kW |

Unrecognised models get the 3.6 kW limits to be safe, and a warning is logged so the model can be added. On parallel systems each maximum is multiplied by the number of inverters. Your battery may set a lower limit, which the inverter enforces itself; for example a single Dura5 is about 5.1 kW.

## Auto Grid Charge

The inverter charges from the grid during your cheap window and stops at **Grid Charge Max SoC**. Auto Grid Charge picks that SoC each night from your solar forecast and your usual consumption, so the battery only takes as much cheap energy as tomorrow needs.

**How it decides.** It steps through the day after the charge window in 30-minute slots, from the end of the window until the next one starts. Each slot adds the forecast solar and subtracts your average usage for that hour of the day over the last 7 days, from Home Assistant's long-term statistics. The battery is capped at full, since surplus solar is exported. What happens next depends on the **target strategy** you pick in the options:

- **Minimum** (the default): the lowest starting SoC that never drops below your reserve, plus the safety margin. It buys only what tomorrow needs.
- **Maximum**: the highest starting SoC that doesn't cause any extra solar to be exported for lack of room, less the margin. It buys as much cheap energy as the solar leaves room for, without solar being exported for lack of space, and never goes below the minimum. On days when the solar never fills the battery (most of winter), that means 100 % less the margin. Here the margin is room for more solar than forecast, so the typical (P50) or optimistic (P90) estimate is the cautious choice, not P10.

The target sensor's attributes show both: `minimum_target_soc` and `max_soc_before_margin`.

**Setting it up**
1. Open the Dura-i integration's **Configure** dialog.
2. Choose your **solar forecast for today** and **for tomorrow**. Any sensor works:
   - **Daily total** (kWh or Wh), e.g. from Forecast.Solar or your own template. It's spread across the day in the shape of your own PV output over the last week.
   - **Hourly detail** (Solcast-style `detailedHourly` attribute). It's used hour by hour, with the estimate you pick (P10, P50 or P90).

   Both days are needed because the target is written after midnight, by which point the day being planned has become "today".
3. Set your **usable battery capacity** (14.4 kWh for a Dura16 LV, 4.6 kWh per Dura5), the **target strategy** and the safety margin. The reserve comes from the inverter's own **Battery Reserve SoC** setting (register 8475), so there's nothing to set; until it has been read, 20 % is used.
4. Tell it when your cheap window is, in one of two ways:
   - **Recommended: a schedule helper** (Settings → Devices & services → Helpers → Schedule) that is on during your cheap window, chosen as the **Charge window schedule**. The target is calculated and written the moment the schedule turns on, when the window's end is known exactly. Changing the schedule, for example when the tariff times move with the seasons, needs nothing else.
   - **Fixed times:** set the window start and end, and **Calculate and set the target at** to a time before the earliest window start (default 00:45).
5. Watch **Auto Grid Charge Target SoC** for a few days. Its attributes show the forecast solar, expected use, the SoC needed before the margin, and which window it planned for.
6. When you're happy with it, enable the **Auto Grid Charge** switch (disabled by default). It then writes the target to Grid Charge Max SoC each night. Turning it off leaves Grid Charge Max SoC at its last value.

**Keeping the charge window set.** The inverter clears Charge Window 1 to 00:00–00:00 about 10 seconds after each window ends, so without help it won't grid-charge the next night. Turn on the **Keep Charge Window Set** switch (disabled by default) and the integration writes the window back: a minute after each window ends, as the next one opens, and on every 30-minute refresh if it has been cleared or changed. It uses the same window as the planner, from the schedule helper or the fixed times, rounded to the minute. This works separately from Auto Grid Charge, so you can keep the window set while choosing Grid Charge Max SoC yourself. Its attributes show the window it will keep. With a schedule helper, the window's length comes from the schedule's last full on period in the recorder; until one has been seen, the window is left alone. While the switch is on, a window changed in the app is put back within 30 minutes.

**Charging late in the window.** By default the battery charges as soon as the window opens, then sits full for hours while the grid runs the house. Turn on **Delay Grid Charge Start** (disabled by default) to move the window's start later, so the battery reaches its set point about 30 minutes before the window ends. From 30 minutes before the window opens, the start is re-planned every minute from the current SoC, the set point (the Auto Grid Charge target while that switch is on, otherwise Grid Charge Max SoC), the lower of Grid and Battery Max Charge Power, and how much the battery is expected to drain before charging starts (your usual usage for that hour). It assumes the battery charges at full set power, but allows 25 % extra charge time in case the battery holds it lower (a smaller or cold battery, for example). With the 30 minutes before the window ends, that covers charging at about 70 % of the set power, at the cost of usually finishing a little early. Once charging has started the start isn't touched again, and the window keeps its usual end, so a slower charge still has until then. The charge rate is learned from each night's charge (SoC % per kWh, shown as `learned_soc_per_kwh`); until then a cautious guess is used that starts a little early. The switch's attributes show tonight's planned start and the rates it used. It keeps the window set as well, so it works with or without **Keep Charge Window Set**.

The trade-off: before charging starts, the battery runs the house, and that energy is then put back from the grid. It's all at the cheap rate, but the round trip loses roughly 10–15 %, so expect a few pence a night and a slightly deeper cycle.

Nothing is chosen for you: the planner stays off until you pick the forecast sensors and set the capacity. Usage comes from the integration's own **Current Load** sensor unless you choose another energy or power sensor.

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
