#!/usr/bin/env python3
"""
Unit and integration tests for the SIL cockpit and CAN simulation stack.
Supports execution via pytest or direct script invocation.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Force Qt offscreen platform before importing GUI modules
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import can
import cantools
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from can_bus import ShmCanBus
from cockpit_display import CockpitWidget
from ecu_core import DBC_PATH, DRIVE_MODES, VehicleSimulation


class TestAutomotiveNetwork(unittest.TestCase):
    """Verify network DBC definitions and message encoding/decoding."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = cantools.database.load_file(DBC_PATH)

    def test_dbc_messages_exist(self) -> None:
        telemetry = self.db.get_message_by_name("PowertrainTelemetry")
        diagnostics = self.db.get_message_by_name("VehicleDiagnostics")
        self.assertEqual(telemetry.frame_id, 256)
        self.assertEqual(diagnostics.frame_id, 512)

    def test_telemetry_encoding_roundtrip(self) -> None:
        msg = self.db.get_message_by_name("PowertrainTelemetry")
        sample = {
            "VehicleSpeed": 105.4,
            "EngineRPM": 3200.0,
            "CurrentGear": 4,
            "TurboBoostBar": 1.15,
            "ThrottlePosition": 45.0,
        }
        encoded = msg.encode(sample)
        decoded = msg.decode(encoded)
        self.assertAlmostEqual(decoded["VehicleSpeed"], 105.4, delta=0.2)
        self.assertEqual(decoded["EngineRPM"], 3200)
        self.assertEqual(decoded["CurrentGear"], 4)
        self.assertAlmostEqual(decoded["TurboBoostBar"], 1.15, delta=0.02)

    def test_diagnostics_encoding_roundtrip(self) -> None:
        msg = self.db.get_message_by_name("VehicleDiagnostics")
        sample = {
            "CoolantTemperature": 92.0,
            "EngineOilPressure": 3.4,
            "FuelTankLevel": 80.0,
            "ActiveDTCAlert": 0,
            "DriveModeSelect": 1,
        }
        encoded = msg.encode(sample)
        decoded = msg.decode(encoded, decode_choices=True)
        self.assertAlmostEqual(decoded["CoolantTemperature"], 92.0, delta=1.0)
        self.assertEqual(str(decoded["DriveModeSelect"]), "Sport")


class TestVehiclePhysics(unittest.TestCase):
    """Test vehicle dynamics simulation states and range constraints."""

    def test_step_dynamics_all_modes(self) -> None:
        for mode in DRIVE_MODES:
            sim = VehicleSimulation(mode)
            for _ in range(50):
                powertrain, diagnostics = sim.step(0.02)

            self.assertGreaterEqual(powertrain["VehicleSpeed"], 0.0)
            self.assertLessEqual(powertrain["VehicleSpeed"], 300.0)
            self.assertGreaterEqual(powertrain["EngineRPM"], 800.0)
            self.assertLessEqual(powertrain["EngineRPM"], 9000.0)
            self.assertIn(powertrain["CurrentGear"], range(1, 7))
            self.assertGreaterEqual(powertrain["TurboBoostBar"], 0.0)
            self.assertLessEqual(powertrain["TurboBoostBar"], 3.0)
            self.assertGreaterEqual(diagnostics["CoolantTemperature"], -40.0)
            self.assertLessEqual(diagnostics["CoolantTemperature"], 215.0)


class TestSharedMemoryBus(unittest.TestCase):
    """Verify cross-process IPC ring buffer message exchange."""

    def test_send_and_receive(self) -> None:
        chan = f"test_shm_{os.getpid()}"
        bus_tx = ShmCanBus(channel=chan)
        bus_rx = ShmCanBus(channel=chan)

        tx_msg = can.Message(
            arbitration_id=0x1AA,
            data=b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE",
            is_extended_id=False,
        )
        bus_tx.send(tx_msg)
        rx_msg = bus_rx.recv(timeout=1.0)

        self.assertIsNotNone(rx_msg)
        assert rx_msg is not None
        self.assertEqual(rx_msg.arbitration_id, 0x1AA)
        self.assertEqual(bytes(rx_msg.data), b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE")

        bus_tx.shutdown()
        bus_rx.shutdown()


class TestCockpitRendering(unittest.TestCase):
    """Test Qt painter execution across telemetry conditions and DTC alerts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.db = cantools.database.load_file(DBC_PATH)

    def test_paint_cycle(self) -> None:
        widget = CockpitWidget()
        widget.resize(1200, 760)

        diag_msg = self.db.get_message_by_name("VehicleDiagnostics")
        pt_msg = self.db.get_message_by_name("PowertrainTelemetry")

        # 1. Nominal frame
        widget.update_from_frame(
            pt_msg.decode(pt_msg.encode({
                "VehicleSpeed": 72.0, "EngineRPM": 2800.0,
                "CurrentGear": 3, "TurboBoostBar": 0.6, "ThrottlePosition": 30.0,
            }), decode_choices=True)
        )
        img = QImage(1200, 760, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        widget.render(painter)
        painter.end()

        # 2. DTC Overheat condition (NamedSignalValue 'Active')
        widget.update_from_frame(
            diag_msg.decode(diag_msg.encode({
                "CoolantTemperature": 110.0, "EngineOilPressure": 2.2,
                "FuelTankLevel": 45.0, "ActiveDTCAlert": 1, "DriveModeSelect": 1,
            }), decode_choices=True)
        )
        painter = QPainter(img)
        widget.render(painter)
        painter.end()

        # 3. Redline state (> 7800 RPM)
        widget.update_from_frame(
            pt_msg.decode(pt_msg.encode({
                "VehicleSpeed": 230.0, "EngineRPM": 8300.0,
                "CurrentGear": 5, "TurboBoostBar": 2.2, "ThrottlePosition": 100.0,
            }), decode_choices=True)
        )
        painter = QPainter(img)
        widget.render(painter)
        painter.end()


if __name__ == "__main__":
    unittest.main(verbosity=2)
