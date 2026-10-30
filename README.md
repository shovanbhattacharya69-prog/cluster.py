# Automotive CAN Digital Instrument Cluster & SIL Simulation

[![CI / Automotive SIL Test Pipeline](https://github.com/shovanbhattacharya69-prog/cluster.py/actions/workflows/ci.yml/badge.svg)](https://github.com/shovanbhattacharya69-prog/cluster.py/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6%2060FPS-41CD52?logo=qt&logoColor=white)
![CAN Protocol](https://img.shields.io/badge/CAN-Vector%20DBC%20%2F%20SocketCAN-FF6F00)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A production-ready Software-in-the-Loop (SIL) automotive cockpit platform targeted for Tier-1 digital instrument clusters (e.g., Visteon SmartCore). Built with high-performance antialiased PyQt6 graphics and a physics-based powertrain ECU plant model communicating over a standardized Controller Area Network (CAN) interface.

---

## Architecture & System Overview

The project simulates an automotive in-vehicle Electronic Control Unit (ECU) network topology:

1. **Powertrain & Diagnostics ECU (`ecu_core.py`)**: A continuous-time physics simulation node modeling aerodynamic resistance, engine torque curves, automatic 6-speed transmission shifting, turbocharger spool lag, thermal dissipation, and diagnostic trouble code (DTC) alert conditions.
2. **Digital Instrument Cluster (`cockpit_display.py`)**: A native 60 FPS desktop cluster displaying dual analog-style sweep gauges, progressive 12-segment shift lights, turbo boost meter, vital fluid diagnostics, and active DTC fault banners.
3. **Hardware Abstraction Layer (`can_bus.py`)**: Seamless transport layer utilizing Linux kernel SocketCAN (`vcan0`) and high-throughput POSIX/Windows shared-memory ring buffers (`ShmCanBus`) for driverless multi-process simulation on macOS and Windows.

```
   +-------------------------+              +-------------------------+
   |    Powertrain ECU       |              |   Instrument Cluster    |
   |     (ecu_core.py)       |              |  (cockpit_display.py)   |
   +------------+------------+              +------------+------------+
                |                                        |
                |   CAN ID 0x100: Powertrain (50 Hz)     |
                |   CAN ID 0x200: Diagnostics (20 Hz)    |
                +===================+====================+
                                    |
                    CAN Bus Transport (can_bus.py)
                    - Linux: Native SocketCAN (vcan0)
                    - Windows/macOS: Shared-Memory IPC Ring
```

---

## Network Specification (Vector DBC)

Frames and signals are strictly serialized and deserialized using [`automotive_network.dbc`](automotive_network.dbc):

| Message Name | Arbitration ID | Cycle Time | Length | Signals & Calibration Range |
| :--- | :--- | :--- | :--- | :--- |
| **`PowertrainTelemetry`** | `0x100` (256) | 20 ms (50 Hz) | 8 Bytes | • `VehicleSpeed`: 0–300 km/h (0.1 scale)<br>• `EngineRPM`: 0–9000 rpm (1 scale)<br>• `CurrentGear`: 1–6 (1 scale)<br>• `TurboBoostBar`: 0–3.00 bar (0.01 scale)<br>• `ThrottlePosition`: 0–100% (0.5 scale) |
| **`VehicleDiagnostics`** | `0x200` (512) | 50 ms (20 Hz) | 50 ms (20 Hz) | • `CoolantTemperature`: -40–215 °C (1 scale, -40 offset)<br>• `EngineOilPressure`: 0–10.0 bar (0.01 scale)<br>• `FuelTankLevel`: 0–100% (1 scale)<br>• `ActiveDTCAlert`: 0=Inactive, 1=Active<br>• `DriveModeSelect`: 0=Eco, 1=Sport, 2=Track |

---

## Getting Started

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Standard C runtime and graphical display driver (or offscreen driver for headless servers)

### Installation

```bash
# Clone the repository
git clone https://github.com/shovanbhattacharya69-prog/cluster.py.git
cd cluster.py

# Create and activate virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Operating Modes

### 1. Unified Cockpit Launcher (Recommended)

Runs the instrument cluster UI with the ECU plant simulation executing asynchronously in a dedicated worker thread:

```bash
python run.py --drive-mode Sport
```

**Options:**
- `--drive-mode {Eco,Sport,Track}`: Set dynamic calibration profile.
- `--fullscreen`: Launch in immersive fullscreen display mode (Toggle anytime with `F11`; exit with `Esc`).

### 2. Multi-Process Software-in-the-Loop (SIL)

Simulates separate physical hardware ECUs communicating over the virtual CAN bus in isolated processes:

**Terminal 1 — Powertrain Simulation Node:**
```bash
python ecu_core.py --drive-mode Track
```

**Terminal 2 — Digital Instrument Cluster:**
```bash
python cockpit_display.py
```

The cluster automatically establishes bus arbitration, indicators turn to `CAN ONLINE`, and streams incoming telemetry at 50 FPS.

---

## Driving Profiles

The vehicle plant dynamics and cockpit styling adapt dynamically across driving modes:

| Drive Mode | Accent Color | Shift Point | Throttle Response | Characteristics |
| :--- | :--- | :--- | :--- | :--- |
| **Eco** | Emerald (`#39d98a`) | 6,100 RPM | 0.90x Linear | Smooth acceleration, optimal fuel economy, mild thermals. |
| **Sport** | Amber (`#ffb547`) | 6,900 RPM | 1.00x Linear | Balanced power delivery, responsive boost spooling. |
| **Track** | Crimson (`#ff4d5a`) | 7,600 RPM | 1.20x Aggressive | High boost, rapid gear shifts, flashing shift lights (>7800 RPM). |

---

## Diagnostic Trouble Code (DTC) Injection

When engine coolant temperature surpasses **104 °C** under heavy engine load:
1. `ecu_core.py` sets `ActiveDTCAlert = 1`.
2. The instrument cluster intercepts the diagnostic frame and renders an illuminated warning banner:
   ```
   ⚠ DTC: P0117 (COOLANT OVERHEAT)
   ```
3. Returning engine load to cruise cools the block and automatically clears the DTC indicator.

---

## Verification & Testing

The comprehensive test suite verifies DBC encoding roundtrips, vehicle physics boundary limits, shared-memory IPC buffer reliability, and headless offscreen GUI rendering:

```bash
python -m unittest test_cluster.py
```

Or using `pytest`:
```bash
pytest -v test_cluster.py
```

---

## Repository Structure

```
├── .github/workflows/
│   ├── ci.yml               # Multi-OS CI/CD pipeline (Ubuntu & Windows across Python 3.10-3.12)
│   └── jekyll-gh-pages.yml  # GitHub Pages static site deployment
├── .vscode/
│   └── settings.json        # Workspace configuration & automotive CAN spellcheck rules
├── scripts/
│   └── setup_vcan.sh        # Linux SocketCAN interface setup script
├── automotive_network.dbc   # Vector CANdb++ network definition
├── can_bus.py               # Hardware abstraction layer (SocketCAN & Windows mmap IPC)
├── cockpit_display.py       # PyQt6 cluster GUI and asynchronous CAN receiver thread
├── ecu_core.py              # Powertrain & vehicle dynamics simulation node
├── run.py                   # Subsystem entrypoint launcher
├── test_cluster.py          # Integration and unit test suite
├── pyproject.toml           # PEP 517/518 build specification
├── requirements.txt         # Package dependency specifications
├── LICENSE                  # MIT License
└── README.md                # Project documentation
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
