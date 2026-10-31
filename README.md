# Visteon Software-in-the-Loop Cockpit – CAN Telemetry Cluster

[![Deploy static content to Pages](https://github.com/shovanbhattacharya69-prog/cluster.py/actions/workflows/static.yml/badge.svg)](https://github.com/shovanbhattacharya69-prog/cluster.py/actions/workflows/static.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)
[![Pages Status](https://img.shields.io/badge/Live%20Demo-GitHub%20Pages-brightgreen)](https://shovanbhattacharya69-prog.github.io/cluster.py/)

A professional-grade **Automotive Digital Instrument Cockpit Cluster** and **CAN Bus Telemetry Simulator** built with Python (PyQt6 / python-can / cantools) and demonstrated online via an ultra-premium, interactive HTML5/Tailwind/WebAudio instrument cluster.

---

## 🏎️ Live Interactive Demo

Open the live demonstration in your browser:

👉 **[https://shovanbhattacharya69-prog.github.io/cluster.py/](https://shovanbhattacharya69-prog.github.io/cluster.py/)**

### Interactive Web Features:
* **Anti-Aliased Digital Gauges**: Real-time Speedometer (0–300 km/h or mph) & Tachometer (0–9000 RPM) with smooth sweep physics and redline warnings.
* **12-Segment Sequential Shift Lights**: F1-style LED tachometer indicator (Green ➔ Amber ➔ Red ➔ Crimson flash at limiter).
* **6-Speed Transmission & Boost Gauge**: Gear indicator and dynamic turbo boost (-1.0 to 3.0 bar).
* **Drive Modes**: Switch between **Eco** (emerald), **Sport** (amber), and **Track** (racing crimson) with distinct dynamic calibration curves.
* **Live CAN 2.0B Sniffer**: Real-time streaming hex frame monitor showing CAN ID `0x100` (`PowertrainTelemetry` at 50 Hz) and `0x200` (`VehicleDiagnostics` at 20 Hz).
* **DTC Fault Injection Matrix**: Test MIL check engine triggers, overheat alerts (P0117), oil pressure warnings, and clear fault codes with one click.
* **Interactive Controls & WebAudio**: Use your keyboard (`[Space]` Throttle, `[B]` Brake, `[Q]`/`[E]` Paddle shifters, `[A]`/`[D]` Turn signals) or on-screen pedals with realistic synthesized engine sound.

---

## 🗂️ Project Architecture

```
cluster.py/
├── index.html                   # High-performance web twin of the digital cockpit (Root for Pages)
├── frontend/
│   └── index.html               # Frontend mirror for static distribution
├── .github/
│   └── workflows/
│       ├── static.yml           # Official GitHub Actions Static HTML Pages deployment
│       └── ci.yml               # Automated test suite and linting CI
├── automotive_network.dbc       # Standard CAN network database (IDs 256 & 512)
├── ecu_core.py                  # Powertrain & diagnostics ECU physics simulation node
├── can_bus.py                   # Virtual CAN (SocketCAN / virtual interface) bus layer
├── cockpit_display.py           # PyQt6 native desktop instrument cluster GUI
├── run.py                       # Single-command launcher for ECU + Cockpit
├── test_cluster.py              # Pytest test suite for telemetry and DBC integrity
├── requirements.txt             # Python dependencies
└── pyproject.toml               # Build configuration
```

---

## 📡 CAN Network Specification (`automotive_network.dbc`)

| Frame ID | Name | Cycle | Signals | Description |
|---|---|---|---|---|
| **0x100** (256) | `PowertrainTelemetry` | 20 ms (50 Hz) | `VehicleSpeed`, `EngineRPM`, `CurrentGear`, `TurboBoostBar`, `ThrottlePosition` | High-frequency powertrain state telemetry |
| **0x200** (512) | `VehicleDiagnostics` | 50 ms (20 Hz) | `CoolantTemperature`, `EngineOilPressure`, `FuelTankLevel`, `ActiveDTCAlert`, `DriveModeSelect` | Diagnostics & thermal status; triggers P0117 DTC on overheat |

---

## 💻 Running Desktop App Locally

1. **Clone the repository**:
   ```bash
   git clone https://github.com/shovanbhattacharya69-prog/cluster.py.git
   cd cluster.py
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch the simulator**:
   ```bash
   # Run both ECU core and Cockpit Display together:
   python run.py --mode Sport
   ```

4. **Run tests**:
   ```bash
   pytest test_cluster.py -v
   ```

---

## ⚙️ How GitHub Pages Deployment Works

This repository uses GitHub's official **Static HTML GitHub Actions workflow** (`.github/workflows/static.yml`):
* **Trigger**: Every push to `main` or manual trigger via `workflow_dispatch`.
* **Path**: Deploys root `index.html` directly to GitHub Pages with zero external build step needed.
* **To enable in GitHub Settings**:
  1. Open repository **Settings** ➔ **Pages**.
  2. Under **Build and deployment** ➔ **Source**, select **GitHub Actions**.
  3. The `static.yml` workflow will automatically run and publish the site.

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
