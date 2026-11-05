# Solis / Skyline / Duracell Dura-i Modbus Register Reference

This document serves as a comprehensive Modbus TCP/RTU register specification for Solis hybrid inverters integrated with Duracell Dura16 / Skyline energy storage systems.

---

## 1. Connection & Protocol Settings

* **Protocol:** Modbus TCP / RTU (RS485)
* **Default Slave ID (Unit ID):** `1`
* **Default Modbus TCP Port:** `502`
* **Byte Order:** Big-Endian (High byte first)
* **Function Codes:**
  * `03` (`0x03`): Read Holding Registers
  * `04` (`0x04`): Read Input Registers
  * `06` (`0x06`): Write Single Holding Register
  * `16` (`0x10`): Write Multiple Holding Registers

---

## 2. Holding Registers (Read / Write Controls)

Holding registers control inverter operating modes, charge/discharge time slots, power limits, and State of Charge (SoC) parameters.

| Register (Dec) | Register (Hex) | Parameter Description | Range / Unit | Data Type | Scale / Format | Notes & Typical Values |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`8450`** | `0x2102` | Slot 1 Grid Charge Start Time | `0` – `5915` | `uint16` | $HH \times 256 + MM$ | e.g., `512` = 02:00 AM |
| **`8451`** | `0x2103` | Slot 1 Grid Charge Stop Time | `0` – `5915` | `uint16` | $HH \times 256 + MM$ | e.g., `2048` = 08:00 AM |
| **`8452`** | `0x2104` | Slot 1 Charge Current Limit | `0` – `1000` ($0.1\text{ A}$) | `uint16` | $0.1$ | `0` = Unrestricted (use max active cap) |
| **`8453`** | `0x2105` | Slot 1 Discharge Start Time | `0` – `5915` | `uint16` | $HH \times 256 + MM$ | e.g., `4608` = 18:00 PM |
| **`8454`** | `0x2106` | Slot 1 Discharge Stop Time | `0` – `5915` | `uint16` | $HH \times 256 + MM$ | e.g., `5888` = 23:00 PM |
| **`8455`** | `0x2107` | Slot 1 Discharge Current Limit | `0` – `1000` ($0.1\text{ A}$) | `uint16` | $0.1$ | `0` = Unrestricted |
| **`8470`** | `0x2116` | Grid Charge Max Power | `0` – `6600` ($\text{W}$) | `uint16` | $1$ | Caps AC grid import for battery charge (e.g., `3680` = 16A G98 limit) |
| **`8474`** | `0x211A` | Max Charge Active Power | `0` – `6600` ($\text{W}$) | `uint16` | $1$ | Global active charging power limit (default `6600`) |
| **`8475`** | `0x211B` | Battery Reserve Floor | `0` – `100` ($\%$) | `uint16` | $1$ | Preserves min SOC; prevents deep discharge (e.g., `15`) |
| **`8485`** | `0x2125` | Max Charge Limit Power | `0` – `9000` ($\text{W}$) | `uint16` | $1$ | Hard hardware safety power limit |
| **`8493`** | `0x212D` | Max Depth of Discharge (DoD) | `0` – `100` ($\%$) | `uint16` | $1$ | Set to $100 - \text{Reserve Floor}$ (e.g., `85` for 15% reserve) |
| **`8494`** | `0x212E` | Force Charge / Control Mode | `0`, `1`, `2` | `uint16` | Enum | `0` = Self-Use / Auto, `1` = Force Charge, `2` = Force Discharge |
| **`8495`** | `0x212F` | Force Charge Current Limit | `0` – `1000` ($0.1\text{ A}$) | `uint16` | $0.1$ | Current cap during manual force charge (e.g., `430` = 43.0A) |
| **`8504`** | `0x2138` | Force Charge Target SoC | `0` – `100` ($\%$) | `uint16` | $1$ | Target state of charge for force charge cycles (e.g., `20` or `100`) |
| **`8505`** | `0x2139` | Grid Charge End SoC | `0` – `100` ($\%$) | `uint16` | $1$ | Stop grid charge when reached (e.g., `85` or `100`) |

---

## 3. Input Registers (Read-Only Telemetry & Clock)

Input registers provide system operation telemetry, power flow measurements, battery status, and internal Real-Time Clock (RTC) values.

### Inverter Real-Time Clock (RTC)

| Register (Dec) | Register (Hex) | Parameter Description | Expected Range | Data Type |
| :--- | :--- | :--- | :--- | :--- |
| **`3021`** | `0x0BCD` | System Year | `2000` – `2099` (or `0` – `99`) | `uint16` |
| **`3022`** | `0x0BCE` | System Month | `1` – `12` | `uint16` |
| **`3023`** | `0x0BCF` | System Day | `1` – `31` | `uint16` |
| **`3024`** | `0x0BD0` | System Hour | `0` – `23` | `uint16` |
| **`3025`** | `0x0BD1` | System Minute | `0` – `59` | `uint16` |
| **`3026`** | `0x0BD2` | System Second | `0` – `59` | `uint16` |

### System Telemetry & Power Flows

| Register (Dec) | Register (Hex) | Parameter Description | Unit | Scale / Format | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`33022`** | `0x8106` | Inverter Temperature | $^\circ\text{C}$ | $0.1$ | Signed integer |
| **`33049`** | `0x8121` | Active PV Power | $\text{W}$ | $1$ | Total solar power generated |
| **`33055`** | `0x8127` | Grid Active Power | $\text{W}$ | $1$ | Positive = Export, Negative = Import |
| **`33126`** | `0x8166` | Battery Voltage | $\text{V}$ | $0.1$ | Nominal pack DC voltage (~$51.2\text{ V}$) |
| **`33127`** | `0x8167` | Battery Current | $\text{A}$ | $0.1$ | Positive = Charge, Negative = Discharge |
| **`33128`** | `0x8168` | Battery Power / Load | $\text{W}$ | $1$ | Negative = Charging, Positive = Discharging |
| **`33139`** | `0x8173` | Battery State of Charge (SOC) | $\%$ | $1$ | Current battery percentage (`0` – `100`) |
| **`33140`** | `0x8174` | Battery State of Health (SOH) | $\%$ | $1$ | Battery pack capacity health rating |

---

## 4. BMS Cell Health & Balancing Registers

These registers pull direct cell telemetry passed from the Dura16 BMS over CAN/RS485 to the inverter interface.

| Register (Dec) | Register (Hex) | Parameter Description | Unit | Scale | Safe Operating Range |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`33141`** | `0x8175` | BMS Maximum Cell Voltage | $\text{V}$ | $0.001$ | $3.150\text{ V} - 3.450\text{ V}$ |
| **`33142`** | `0x8176` | BMS Minimum Cell Voltage | $\text{V}$ | $0.001$ | $2.950\text{ V} - 3.450\text{ V}$ ($\ge 2.85\text{ V}$ cutoff) |

---

## 5. Time Encoding & Conversion Rules

Charge and discharge time registers (`8450`, `8451`, `8453`, `8454`) use a packed 16-bit integer format combining hours and minutes into a single register value.

### Mathematical Formula

$$\text{Packed Register Value} = (\text{Hour} \times 256) + \text{Minute}$$

### Standard Time Slot Lookup Table

| Target Time ($HH:MM$) | Calculation | Register Value |
| :--- | :--- | :--- |
| **00:00** | $(0 \times 256) + 0$ | **`0`** |
| **00:30** | $(0 \times 256) + 30$ | **`30`** |
| **02:00** | $(2 \times 256) + 0$ | **`512`** |
| **05:30** | $(5 \times 256) + 30$ | **`1310`** |
| **07:30** | $(7 \times 256) + 30$ | **`1822`** |
| **08:00** | $(8 \times 256) + 0$ | **`2048`** |
| **23:30** | $(23 \times 256) + 30$ | **`5918`** |

---
