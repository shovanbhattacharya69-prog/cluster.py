#!/usr/bin/env python3
"""Software-in-the-loop ECU simulator for the cockpit CAN network."""

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

LOGGER = logging.getLogger("ecu_core")
DBC_PATH = Path(__file__).with_name("automotive_network.dbc")
TELEMETRY_PERIOD = 1.0 / 50.0
DIAGNOSTICS_PERIOD = 1.0 / 20.0
DRIVE_MODES = {"Eco": 0, "Sport": 1, "Track": 2}


class VehicleSimulation:
    """Deterministic, time-stepped vehicle dynamics for repeatable SIL runs."""

    _GEAR_RPM_PER_KMH = (82.0, 54.0, 39.0, 30.0, 24.0, 20.0)
    _MODE_LIMITS = {
        "Eco": (6100.0, 1450.0, 0.9),
        "Sport": (6900.0, 1750.0, 1.0),
        "Track": (7600.0, 2050.0, 1.2),
    }

    def __init__(self, drive_mode: str) -> None:
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
        self._load_average = 0.25

    def step(self, dt: float) -> tuple[dict[str, float | int], dict[str, float | int]]:
        """Advance the simulated plant and return physical DBC signal values."""
        dt = min(max(dt, 0.0), 0.1)
        self._elapsed_s += dt

        throttle = 0.30 + 0.23 * math.sin(self._elapsed_s * 0.17)
        throttle += 0.10 * math.sin(self._elapsed_s * 0.047 + 1.2)
        throttle = min(max(throttle, 0.04), 0.72)
        upshift_rpm, downshift_rpm, acceleration_scale = self._MODE_LIMITS[
            self.drive_mode
        ]

        speed_kmh = self.speed_mps * 3.6
        rpm_per_kmh = self._GEAR_RPM_PER_KMH[self.gear - 1]
        estimated_rpm = 800.0 + speed_kmh * rpm_per_kmh
        if self.gear < len(self._GEAR_RPM_PER_KMH) and estimated_rpm >= upshift_rpm:
            self.gear += 1
        elif self.gear > 1 and estimated_rpm < downshift_rpm:
            self.gear -= 1

        load = min(max(throttle * acceleration_scale, 0.0), 1.0)
        self._load_average += (load - self._load_average) * min(dt / 2.0, 1.0)
        acceleration = (throttle * 4.5 * acceleration_scale) - (
            0.014 * self.speed_mps
        ) - 0.16
        self.speed_mps = min(max(self.speed_mps + acceleration * dt, 0.0), 82.0)
        speed_kmh = self.speed_mps * 3.6

        rpm_per_kmh = self._GEAR_RPM_PER_KMH[self.gear - 1]
        self.engine_rpm = min(
            max(800.0 + speed_kmh * rpm_per_kmh + 550.0 * load, 800.0),
            9000.0,
        )

        target_boost = min(3.0, max(0.0, (load - 0.12) * 3.15))
        turbo_time_constant = 0.75 if target_boost > self.boost_bar else 1.7
        self.boost_bar += (
            (target_boost - self.boost_bar) * min(dt / turbo_time_constant, 1.0)
        )

        ambient_c = 22.0
        target_coolant_c = ambient_c + 84.0 + 45.0 * self._load_average
        target_coolant_c -= min(speed_kmh * 0.035, 14.0)
        thermal_time_constant = 240.0 if target_coolant_c > self.coolant_c else 360.0
        self.coolant_c += (
            (target_coolant_c - self.coolant_c)
            * min(dt / thermal_time_constant, 1.0)
        )
        self.coolant_c = min(max(self.coolant_c, -40.0), 215.0)

        self.oil_pressure_bar = min(
            10.0, max(0.0, 0.8 + self.engine_rpm / 2600.0)
        )
        self.fuel_percent = max(
            0.0, self.fuel_percent - (0.000035 + 0.00015 * load) * dt
        )

        powertrain: dict[str, float | int] = {
            "VehicleSpeed": min(speed_kmh, 300.0),
            "EngineRPM": self.engine_rpm,
            "CurrentGear": self.gear,
            "TurboBoostBar": self.boost_bar,
            "ThrottlePosition": throttle * 100.0,
        }
        diagnostics: dict[str, float | int] = {
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
    """Run the vehicle simulation publishing telemetry and diagnostics frames."""
    database = cantools.database.load_file(dbc_path)
    telemetry_message = database.get_message_by_name("PowertrainTelemetry")
    diagnostics_message = database.get_message_by_name("VehicleDiagnostics")
    simulator = VehicleSimulation(drive_mode)

    own_bus = bus is None
    if bus is None:
        bus = create_bus()

    stopped = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True

    try:
        signal.signal(signal.SIGINT, request_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_stop)
    except (ValueError, AttributeError):
        pass  # In thread or non-main process

    LOGGER.info(
        "ECU simulator running in %s mode; telemetry 50 Hz, diagnostics 20 Hz.",
        drive_mode,
    )
    started_at = time.monotonic()
    next_telemetry_at = started_at
    next_diagnostics_at = started_at
    previous_step_at = started_at
    try:
        while not stopped:
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                break

            now = time.monotonic()
            if now < next_telemetry_at:
                time.sleep(min(max(next_telemetry_at - now, 0.0), 0.005))
                continue

            dt = now - previous_step_at
            previous_step_at = now
            powertrain, diagnostics = simulator.step(dt)

            telemetry_data = telemetry_message.encode(powertrain, strict=True)
            bus.send(
                can.Message(
                    arbitration_id=telemetry_message.frame_id,
                    data=telemetry_data,
                    is_extended_id=False,
                ),
                timeout=0.1,
            )
            next_telemetry_at += TELEMETRY_PERIOD
            if now >= next_diagnostics_at:
                diagnostics_data = diagnostics_message.encode(diagnostics, strict=True)
                bus.send(
                    can.Message(
                        arbitration_id=diagnostics_message.frame_id,
                        data=diagnostics_data,
                        is_extended_id=False,
                    ),
                    timeout=0.1,
                )
                next_diagnostics_at += DIAGNOSTICS_PERIOD

            if now - next_telemetry_at > TELEMETRY_PERIOD:
                next_telemetry_at = now + TELEMETRY_PERIOD
            if now - next_diagnostics_at > DIAGNOSTICS_PERIOD:
                next_diagnostics_at = now + DIAGNOSTICS_PERIOD
    finally:
        if own_bus and bus is not None:
            bus.shutdown()
        LOGGER.info("ECU simulator stopped.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drive-mode",
        choices=tuple(DRIVE_MODES),
        default="Sport",
        help="Simulated drive mode (default: Sport).",
    )
    parser.add_argument(
        "--dbc",
        type=Path,
        default=DBC_PATH,
        help="DBC file to load (default: automotive_network.dbc beside this script).",
    )
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_simulation(drive_mode=args.drive_mode, dbc_path=args.dbc)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        LOGGER.info("ECU simulator stopped by user.")
        sys.exit(0)
    except (OSError, RuntimeError, can.CanError, cantools.database.errors.Error) as exc:
        LOGGER.error("ECU simulator failed: %s", exc)
        sys.exit(1)
