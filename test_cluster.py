#!/usr/bin/env python3
"""Comprehensive test suite for the cockpit cluster project."""

import os
import sys
import time
from pathlib import Path

# Run Qt offscreen for automated testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import can
import cantools
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from can_bus import ShmCanBus, create_bus
from cockpit_display import CockpitWidget, DEFAULT_VALUES
from ecu_core import DBC_PATH, DRIVE_MODES, VehicleSimulation


def test_dbc_loading() -> None:
    print("Testing DBC loading and message schemas...")
    db = cantools.database.load_file(DBC_PATH)
    assert db.get_message_by_name("PowertrainTelemetry") is not None
    assert db.get_message_by_name("VehicleDiagnostics") is not None
    print("[PASS] DBC loaded successfully.")


def test_vehicle_simulation() -> None:
    print("Testing vehicle dynamics simulation across modes...")
    for mode in DRIVE_MODES:
        sim = VehicleSimulation(mode)
        powertrain, diagnostics = sim.step(0.02)
        assert 0.0 <= powertrain["VehicleSpeed"] <= 300.0
        assert 800.0 <= powertrain["EngineRPM"] <= 9000.0
        assert 1 <= powertrain["CurrentGear"] <= 6
        assert 0.0 <= powertrain["TurboBoostBar"] <= 3.0
        assert -40.0 <= diagnostics["CoolantTemperature"] <= 215.0
        assert 0.0 <= diagnostics["EngineOilPressure"] <= 10.0
        assert 0.0 <= diagnostics["FuelTankLevel"] <= 100.0
        assert diagnostics["ActiveDTCAlert"] in (0, 1)
        assert diagnostics["DriveModeSelect"] == DRIVE_MODES[mode]
    print("[PASS] Vehicle simulation validated.")


def test_shm_can_bus() -> None:
    print("Testing shared-memory virtual CAN bus...")
    bus1 = ShmCanBus(channel="test_bus")
    bus2 = ShmCanBus(channel="test_bus")

    test_msg = can.Message(
        arbitration_id=0x123,
        data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        is_extended_id=False,
    )
    bus1.send(test_msg)
    recv_msg = bus2.recv(timeout=1.0)

    assert recv_msg is not None, "Failed to receive message on bus2"
    assert recv_msg.arbitration_id == 0x123
    assert bytes(recv_msg.data) == b"\x01\x02\x03\x04\x05\x06\x07\x08"
    bus1.shutdown()
    bus2.shutdown()
    print("[PASS] Shared-memory CAN bus validated.")


def test_cockpit_widget_render() -> None:
    print("Testing CockpitWidget rendering across multiple frames and DTC alert states...")
    app = QApplication.instance() or QApplication([])
    widget = CockpitWidget()
    widget.resize(1200, 760)

    db = cantools.database.load_file(DBC_PATH)
    t_msg = db.get_message_by_name("PowertrainTelemetry")
    d_msg = db.get_message_by_name("VehicleDiagnostics")

    # Test Eco mode normal
    widget.update_from_frame(
        t_msg.decode(
            t_msg.encode({
                "VehicleSpeed": 95.0,
                "EngineRPM": 2400.0,
                "CurrentGear": 4,
                "TurboBoostBar": 0.8,
                "ThrottlePosition": 35.0,
            }),
            decode_choices=True,
        )
    )
    widget.update_from_frame(
        d_msg.decode(
            d_msg.encode({
                "CoolantTemperature": 90.0,
                "EngineOilPressure": 3.5,
                "FuelTankLevel": 85.0,
                "ActiveDTCAlert": 0,
                "DriveModeSelect": 0,
            }),
            decode_choices=True,
        )
    )

    img = QImage(1200, 760, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    widget.render(painter)
    painter.end()

    # Test Sport mode with DTC Overheat alert (causes NamedSignalValue Active)
    widget.update_from_frame(
        d_msg.decode(
            d_msg.encode({
                "CoolantTemperature": 108.0,
                "EngineOilPressure": 2.8,
                "FuelTankLevel": 60.0,
                "ActiveDTCAlert": 1,
                "DriveModeSelect": 1,
            }),
            decode_choices=True,
        )
    )
    painter = QPainter(img)
    widget.render(painter)
    painter.end()

    # Test Track mode high RPM shift light flash
    widget.update_from_frame(
        t_msg.decode(
            t_msg.encode({
                "VehicleSpeed": 240.0,
                "EngineRPM": 8200.0,
                "CurrentGear": 6,
                "TurboBoostBar": 2.4,
                "ThrottlePosition": 95.0,
            }),
            decode_choices=True,
        )
    )
    widget.update_from_frame(
        d_msg.decode(
            d_msg.encode({
                "CoolantTemperature": 102.0,
                "EngineOilPressure": 4.8,
                "FuelTankLevel": 40.0,
                "ActiveDTCAlert": 0,
                "DriveModeSelect": 2,
            }),
            decode_choices=True,
        )
    )
    painter = QPainter(img)
    widget.render(painter)
    painter.end()

    print("[PASS] CockpitWidget rendering verified without errors.")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING COCKPIT PROJECT TEST SUITE")
    print("=" * 60)
    test_dbc_loading()
    test_vehicle_simulation()
    test_shm_can_bus()
    test_cockpit_widget_render()
    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! PROJECT IS READY TO RUN.")
    print("=" * 60)
