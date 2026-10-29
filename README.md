# Visteon SIL Cockpit & ECU Simulator

A Software-in-the-Loop (SIL) automotive instrument cluster with an integrated powertrain & diagnostics ECU simulator connected over a virtual CAN bus.

## Features

- **High-Fidelity Dashboard UI**: Custom antialiased PyQt6 instrument cluster rendering speed, RPM, gear, turbo boost, coolant temperature, oil pressure, fuel level, shift lights, and active DTC fault indicators.
- **Dynamic ECU Simulation**: Deterministic vehicle dynamics model transmitting telemetry at 50 Hz and diagnostics at 20 Hz according to `automotive_network.dbc`.
- **Cross-Process Virtual CAN**: Shared-memory ring buffer (`can_bus.py`) enabling cross-process CAN communication on Windows and Linux without physical hardware or kernel configuration.
- **Multiple Drive Modes**: Selectable Eco, Sport, and Track modes with mode-adaptive redlines, shift points, and accent themes.

---

## Installation

Ensure your Python environment has the required dependencies:

```powershell
pip install -r requirements.txt
```

---

## How to Run

### Option 1: One-Click Launch (All-in-One)
Launch the cockpit display with the ECU simulator running automatically:

```powershell
.\.venv\Scripts\python.exe run.py
```

Or choose a specific drive mode:
```powershell
.\.venv\Scripts\python.exe run.py --drive-mode Track
```

Full-screen mode:
```powershell
.\.venv\Scripts\python.exe run.py --fullscreen
```

---

### Option 2: Running Separate Processes (SIL Testing)

Open **two terminal windows** to simulate physical ECUs talking to the cluster:

**Terminal 1 (ECU Simulator):**
```powershell
.\.venv\Scripts\python.exe ecu_core.py --drive-mode Sport
```

**Terminal 2 (Cockpit Cluster Display):**
```powershell
.\.venv\Scripts\python.exe cockpit_display.py
```

---

### Option 3: Direct Cockpit with Integrated Simulation
```powershell
.\.venv\Scripts\python.exe cockpit_display.py --sim --drive-mode Sport
```

---

## Running Automated Tests

Run the test suite to verify DBC parsing, vehicle dynamics, virtual CAN bus IPC, and UI rendering:

```powershell
.\.venv\Scripts\python.exe test_cluster.py
```
