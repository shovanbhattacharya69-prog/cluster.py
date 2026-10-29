#!/usr/bin/env python3
"""
Powertrain & diagnostics ECU node simulation.

Models vehicle dynamics (speed, RPM, transmission shift logic, boost pressure,
coolant thermals, oil pressure) and broadcasts periodic CAN telemetry and
diagnostic frames according to automotive_network.dbc.
"""

from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
import time
from pathlib import Path

import can
import cantools

from can_bus import create_bus

log = logging.getLogger("ecu_core")
DBC_PATH = Path(__file__).with_name("automotive_network.dbc")

TELEMETRY_INTERVAL = 0.020    # 50 Hz powertrain telemetry
DIAGNOSTICS_INTERVAL = 0.050  # 20 Hz vehicle diagnostics
DRIVE_MODES = {"Eco": 0, "Sport": 1, "Track": 2}


class VehicleSimulation:
    """
    Powertrain and chassis model.
    Calculates engine RPM, 6-speed transmission gearing, turbo spool dynamics,
    and engine thermals under continuous driver throttle inputs.
    """

    # Gear ratios scaled as engine RPM per km/h
    GEAR_RPM_RATIOS = (82.0, 54.0, 39.0, 30.0, 24.0, 20.0)

    # Mode parameters: (upshift_rpm, downshift_rpm, throttle_gain)
    MODE_CALIBRATION = {
        "Eco": (6100.0, 1450.0, 0.90),
        "Sport": (6900.0, 1750.0, 1.00),
        "Track": (7600.0, 2050.0, 1.20),
    }

    def __init__(self, drive_mode: str = "Sport") -> None:
        self.drive_mode = drive_mode
        self.mode_value = DRIVE_MODES[drive_mode]
        self.speed_mps = 0.0
        self.engine_rpm = 800.0
        self.gear = 1
        self.boost_bar = 0.0
        self.coolant_c = 88.0
        self.oil_pressure_bar = 0.0
        self.fuel_percent = 100.0
        self._elapsed_s = 0.0
        self._engine_load = 0.25

    def step(self, dt: float) -> tuple[dict[str, float | int], dict[str, float | int]]:
        """Advance vehicle states by dt seconds and return signal maps."""
        dt = min(max(dt, 0.0), 0.10)
        self._elapsed_s += dt

        # Synthetic throttle pedal cycling between light cruise and full throttle
        throttle = 0.30 + 0.23 * math.sin(self._elapsed_s * 0.17)
        throttle += 0.10 * math.sin(self._elapsed_s * 0.047 + 1.20)
        throttle = min(max(throttle, 0.04), 0.72)

        upshift_rpm, downshift_rpm, throttle_gain = self.MODE_CALIBRATION[self.drive_mode]

        # Transmission shift logic
        speed_kmh = self.speed_mps * 3.6
        rpm_ratio = self.GEAR_RPM_RATIOS[self.gear - 1]
        estimated_rpm = 800.0 + speed_kmh * rpm_ratio
        if self.gear < len(self.GEAR_RPM_RATIOS) and estimated_rpm >= upshift_rpm:
            self.gear += 1
        elif self.gear > 1 and estimated_rpm < downshift_rpm:
            self.gear -= 1

        load = min(max(throttle * throttle_gain, 0.0), 1.0)
        self._engine_load += (load - self._engine_load) * min(dt / 2.0, 1.0)

        # Acceleration with aerodynamic drag & rolling friction
        accel = (throttle * 4.5 * throttle_gain) - (0.014 * self.speed_mps) - 0.16
        self.speed_mps = min(max(self.speed_mps + accel * dt, 0.0), 82.0)
        speed_kmh = self.speed_mps * 3.6

        rpm_ratio = self.GEAR_RPM_RATIOS[self.gear - 1]
        self.engine_rpm = min(
            max(800.0 + speed_kmh * rpm_ratio + 550.0 * load, 800.0),
            9000.0,
        )

        # Turbocharger boost response with spool delay
        target_boost = min(3.0, max(0.0, (load - 0.12) * 3.15))
        spool_tau = 0.75 if target_boost > self.boost_bar else 1.70
        self.boost_bar += (target_boost - self.boost_bar) * min(dt / spool_tau, 1.0)

        # Engine coolant thermal dynamics
        target_coolant = 22.0 + 84.0 + 45.0 * self._engine_load - min(speed_kmh * 0.035, 14.0)
        thermal_tau = 240.0 if target_coolant > self.coolant_c else 360.0
        self.coolant_c += (target_coolant - self.coolant_c) * min(dt / thermal_tau, 1.0)
        self.coolant_c = min(max(self.coolant_c, -40.0), 215.0)

        # Engine oil pressure tracks RPM
        self.oil_pressure_bar = min(10.0, max(0.0, 0.80 + self.engine_rpm / 2600.0))

        # Fuel consumption
        self.fuel_percent = max(0.0, self.fuel_percent - (0.000035 + 0.00015 * load) * dt)

        powertrain = {
            "VehicleSpeed": min(speed_kmh, 300.0),
            "EngineRPM": self.engine_rpm,
            "CurrentGear": self.gear,
            "TurboBoostBar": self.boost_bar,
            "ThrottlePosition": throttle * 100.0,
        }
        diagnostics = {
            "CoolantTemperature": self.coolant_c,
            "EngineOilPressure": self.oil_pressure_bar,
            "FuelTankLevel": self.fuel_percent,
            "ActiveDTCAlert": int(self.coolant_c > 104.0),
            "DriveModeSelect": self.mode_value,
        }
        return powertrain, diagnostics


def run_simulation(
    drive_mode: str = "Sport",
    dbc_path: Path = DBC_PATH,
    bus: can.BusABC | None = None,
    stop_event: object | None = None,
) -> None:
    """Run the ECU simulation loop and transmit CAN frames."""
    db = cantools.database.load_file(dbc_path)
    telemetry_msg = db.get_message_by_name("PowertrainTelemetry")
    diagnostics_msg = db.get_message_by_name("VehicleDiagnostics")
    sim = VehicleSimulation(drive_mode)

    own_bus = bus is None
    if bus is None:
        bus = create_bus()

    stopped = False

    def on_stop_signal(_signum: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True

    try:
        signal.signal(signal.SIGINT, on_stop_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, on_stop_signal)
    except (ValueError, AttributeError):
        pass

    log.info("ECU online [mode: %s] | telemetry: 50Hz, diagnostics: 20Hz", drive_mode)

    start = time.monotonic()
    next_telemetry = start
    next_diagnostics = start
    prev_step = start

    try:
        while not stopped:
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                break

            now = time.monotonic()
            if now < next_telemetry:
                time.sleep(min(max(next_telemetry - now, 0.0), 0.005))
                continue

            dt = now - prev_step
            prev_step = now
            powertrain, diagnostics = sim.step(dt)

            bus.send(
                can.Message(
                    arbitration_id=telemetry_msg.frame_id,
                    data=telemetry_msg.encode(powertrain, strict=True),
                    is_extended_id=False,
                ),
                timeout=0.10,
            )
            next_telemetry += TELEMETRY_INTERVAL

            if now >= next_diagnostics:
                bus.send(
                    can.Message(
                        arbitration_id=diagnostics_msg.frame_id,
                        data=diagnostics_msg.encode(diagnostics, strict=True),
                        is_extended_id=False,
                    ),
                    timeout=0.10,
                )
                next_diagnostics += DIAGNOSTICS_INTERVAL

            # Prevent interval drift if execution was delayed
            if now - next_telemetry > TELEMETRY_INTERVAL:
                next_telemetry = now + TELEMETRY_INTERVAL
            if now - next_diagnostics > DIAGNOSTICS_INTERVAL:
                next_diagnostics = now + DIAGNOSTICS_INTERVAL
    finally:
        if own_bus and bus is not None:
            bus.shutdown()
        log.info("ECU node offline")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automotive ECU Simulation Node")
    parser.add_argument(
        "--drive-mode",
        choices=tuple(DRIVE_MODES),
        default="Sport",
        help="Initial driving profile (default: Sport)",
    )
    parser.add_argument(
        "--dbc",
        type=Path,
        default=DBC_PATH,
        help="Path to network DBC file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_simulation(drive_mode=args.drive_mode, dbc_path=args.dbc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        log.error("ECU crashed: %s", exc)
        sys.exit(1)
