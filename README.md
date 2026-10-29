# Automotive CAN Digital Instrument Cluster & SIL Simulation

A Software-in-the-Loop (SIL) automotive instrument cluster built with PyQt6 and a powertrain ECU simulation node communicating over a virtual CAN network defined by Vector DBC.

---

## Overview

The project simulates an automotive in-vehicle network consisting of two primary ECUs:

1. **Powertrain & Diagnostics ECU (`ecu_core.py`)**: A physics-based plant model simulating vehicle speed, 6-speed transmission gearing, throttle demand, turbocharger spool dynamics, engine thermals, and oil pressure.
2. **Digital Instrument Cluster (`cockpit_display.py`)**: An antialiased PyQt6 dashboard rendering dual analog-style sweep gauges, progressive shift indicator LEDs, boost pressure gauge, fluid monitoring, and active DTC fault warnings.

Communication follows standard automotive CAN conventions specified in [`automotive_network.dbc`](automotive_network.dbc).

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
                    - Windows: Shared-Memory IPC (ShmCanBus)
```

---

## Network Specification (DBC)

| Message | Arbitration ID | Cycle Time | Signals |
| :--- | :--- | :--- | :--- |
| **PowertrainTelemetry** | `0x100` (256) | 20 ms (50 Hz) | `VehicleSpeed` (0–300 km/h)<br>`EngineRPM` (0–9000 rpm)<br>`CurrentGear` (1–6)<br>`TurboBoostBar` (0–3.0 bar)<br>`ThrottlePosition` (0–100%) |
| **VehicleDiagnostics** | `0x200` (512) | 50 ms (20 Hz) | `CoolantTemperature` (-40–215 °C)<br>`EngineOilPressure` (0–10.0 bar)<br>`FuelTankLevel` (0–100%)<br>`ActiveDTCAlert` (0=Inactive, 1=Active)<br>`DriveModeSelect` (0=Eco, 1=Sport, 2=Track) |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Dependencies listed in `requirements.txt`:
  - `PyQt6`
  - `python-can`
  - `cantools`

### Installation

```bash
# Clone the repository
git clone https://github.com/shovan/cluster.git
cd cluster

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

## Usage

### 1. Unified Launcher (Single Command)

Runs the instrument cluster with the ECU plant simulation executing in a background worker thread:

```bash
python run.py
```

Optional arguments:
```bash
# Select a drive mode profile (Eco, Sport, Track)
python run.py --drive-mode Track

# Launch in fullscreen mode
python run.py --fullscreen
```

### 2. Multi-Process SIL Execution (Realistic Dual-Node Test)

To simulate separate hardware ECUs communicating over the network, run the ECU node and display in separate terminal windows:

**Terminal 1 — Powertrain ECU:**
```bash
python ecu_core.py --drive-mode Sport
```

**Terminal 2 — Instrument Cluster Display:**
```bash
python cockpit_display.py
```

The cluster automatically discovers the active CAN channel, switches status to `CAN ONLINE`, and streams incoming telemetry at 50 FPS.

---

## Drive Modes

The simulation calibrates vehicle dynamics and instrument cluster accent styling based on the selected mode:

- **Eco** (Green `#39d98a`): Shift threshold at 6,100 RPM, conservative throttle response, optimal fuel economy.
- **Sport** (Amber `#ffb547`): Shift threshold at 6,900 RPM, linear throttle mapping, standard boost curve.
- **Track** (Red `#ff4d5a`): Shift threshold at 7,600 RPM, aggressive throttle multiplier, high-RPM shift-light flashing above 7,800 RPM.

---

## Running Tests

The test suite validates DBC encoding/decoding, physics models, shared-memory CAN serialization, and offscreen widget rendering:

```bash
python test_cluster.py
```

Compatible with `pytest`:
```bash
pytest test_cluster.py -v
```

---

## File Structure

```
├── automotive_network.dbc   # CAN database definition (telemetry & diagnostic frames)
├── can_bus.py               # Hardware abstraction layer (SocketCAN & Windows mmap IPC)
├── cockpit_display.py       # PyQt6 cluster GUI and CAN receiver thread
├── ecu_core.py              # Powertrain & vehicle dynamics simulation node
├── run.py                   # Subsystem entrypoint launcher
├── test_cluster.py          # Integration and unit test suite
├── requirements.txt         # Project package requirements
└── README.md                # Project documentation
```
