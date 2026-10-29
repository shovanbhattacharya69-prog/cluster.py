#!/usr/bin/env python3
"""
PyQt6 digital instrument cluster display.

Subscribes to live CAN telemetry and diagnostic frames, rendering an interactive
dashboard with analog-style speed/RPM gauges, dynamic shift lights, boost meter,
fluid stats, and active DTC fault banners.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from collections import deque
from pathlib import Path
from threading import Event
from typing import Any

import can
import cantools
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget

from can_bus import create_bus

log = logging.getLogger("cockpit")
DBC_PATH = Path(__file__).with_name("automotive_network.dbc")

MODE_COLORS = {
    "Eco": QColor("#39d98a"),
    "Sport": QColor("#ffb547"),
    "Track": QColor("#ff4d5a"),
}

DEFAULT_TELEMETRY: dict[str, Any] = {
    "VehicleSpeed": 0.0,
    "EngineRPM": 800.0,
    "CurrentGear": 1,
    "TurboBoostBar": 0.0,
    "ThrottlePosition": 0.0,
    "CoolantTemperature": 22.0,
    "EngineOilPressure": 0.0,
    "FuelTankLevel": 100.0,
    "ActiveDTCAlert": 0,
    "DriveModeSelect": "Eco",
}


class CanListener(QThread):
    """Worker thread handling non-blocking CAN reception and frame decoding."""

    frame_received = pyqtSignal(dict)
    listener_error = pyqtSignal(str)
    listener_ready = pyqtSignal()

    def __init__(self, dbc_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dbc_path = dbc_path
        self._stop_event = Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            database = cantools.database.load_file(self._dbc_path)
            bus = create_bus()
        except Exception as exc:
            log.error("Unable to initialize CAN interface: %s", exc)
            self.listener_error.emit(str(exc))
            return

        self.listener_ready.emit()
        try:
            while not self._stop_event.is_set():
                frame = bus.recv(timeout=0.10)
                if frame is None:
                    continue

                try:
                    message = database.get_message_by_frame_id(frame.arbitration_id)
                    decoded = message.decode(frame.data, decode_choices=True)
                except (KeyError, cantools.database.errors.DecodeError, ValueError):
                    continue

                self.frame_received.emit(decoded)
        except Exception as exc:
            if not self._stop_event.is_set():
                log.error("CAN receive failure: %s", exc)
                self.listener_error.emit(str(exc))
        finally:
            bus.shutdown()


class EmbeddedSimulatorThread(QThread):
    """Optional background worker for standalone single-process simulation."""

    def __init__(
        self,
        drive_mode: str = "Sport",
        dbc_path: Path = DBC_PATH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._drive_mode = drive_mode
        self._dbc_path = dbc_path
        self._stop_event = Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        from ecu_core import run_simulation

        try:
            run_simulation(
                drive_mode=self._drive_mode,
                dbc_path=self._dbc_path,
                stop_event=self._stop_event,
            )
        except Exception as exc:
            log.error("Simulation worker encountered an error: %s", exc)


class CockpitWidget(QWidget):
    """Custom-painted instrument cluster canvas."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(820, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.values = DEFAULT_TELEMETRY.copy()
        self._frame_history: deque[float] = deque()
        self._fps = 0
        self._bus_status = "CONNECTING TO CAN"
        self._redline_flash = True

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._refresh_timer.start()

    def set_bus_status(self, text: str) -> None:
        self._bus_status = text
        self.update()

    def update_from_frame(self, decoded: dict[str, Any]) -> None:
        self.values.update(decoded)
        self._frame_history.append(time.monotonic())
        self.update()

    def _on_refresh_tick(self) -> None:
        now = time.monotonic()
        while self._frame_history and now - self._frame_history[0] > 1.0:
            self._frame_history.popleft()
        self._fps = len(self._frame_history)

        if float(self.values.get("EngineRPM", 0.0)) > 7800.0:
            self._redline_flash = not self._redline_flash
        else:
            self._redline_flash = True
        self.update()

    @staticmethod
    def _draw_text(
        painter: QPainter,
        x: float,
        y: float,
        text: str,
        size: int,
        color: QColor,
        weight: QFont.Weight = QFont.Weight.Normal,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    ) -> None:
        font = QFont("Segoe UI", size)
        font.setWeight(weight)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(
            int(x - 250),
            int(y - size - 4),
            500,
            size + 12,
            alignment,
            text,
        )

    @staticmethod
    def _point_on_circle(cx: float, cy: float, radius: float, deg: float) -> tuple[float, float]:
        rad = math.radians(deg)
        return cx + radius * math.cos(rad), cy + radius * math.sin(rad)

    def _draw_gauge(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        radius: float,
        val: float,
        max_val: float,
        label: str,
        unit: str,
        accent: QColor,
        divisions: int,
    ) -> None:
        ratio = min(max(val / max_val, 0.0), 1.0)
        arc_r = radius * 0.82
        steps = max(80, divisions * 12)

        bg_path = QPainterPath()
        fg_path = QPainterPath()

        for i in range(steps + 1):
            f = i / steps
            px, py = self._point_on_circle(cx, cy, arc_r, 135.0 + 270.0 * f)
            (fg_path if f <= ratio else bg_path).moveTo(px, py)
            curr = fg_path if f <= ratio else bg_path
            if i > 0:
                prev_f = (i - 1) / steps
                if (prev_f <= ratio) == (f <= ratio):
                    prev_x, prev_y = self._point_on_circle(cx, cy, arc_r, 135.0 + 270.0 * prev_f)
                    curr.moveTo(prev_x, prev_y)
                    curr.lineTo(px, py)

        pen_w = max(7, int(radius * 0.055))
        painter.setPen(QPen(QColor("#1c2229"), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(bg_path)
        painter.setPen(QPen(accent, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(fg_path)

        # Scale tick marks
        painter.setPen(QPen(QColor("#68727d"), 1.5))
        for tick in range(divisions + 1):
            f = tick / divisions
            deg = 135.0 + 270.0 * f
            outer_x, outer_y = self._point_on_circle(cx, cy, radius * 0.72, deg)
            inner_x, inner_y = self._point_on_circle(cx, cy, radius * 0.66, deg)
            painter.drawLine(int(inner_x), int(inner_y), int(outer_x), int(outer_y))

        # Text readouts
        self._draw_text(
            painter, cx, cy - radius * 0.28, label, max(11, int(radius * 0.105)),
            QColor("#9ba5af"), QFont.Weight.DemiBold
        )
        self._draw_text(
            painter, cx, cy + radius * 0.10, f"{val:.0f}", max(30, int(radius * 0.34)),
            QColor("#f2f5f7"), QFont.Weight.Bold
        )
        self._draw_text(
            painter, cx, cy + radius * 0.32, unit, max(11, int(radius * 0.11)),
            QColor("#89939d")
        )

        # Needle indicator
        nx, ny = self._point_on_circle(cx, cy, radius * 0.61, 135.0 + 270.0 * ratio)
        painter.setPen(QPen(QColor("#f5f7f8"), max(2, int(radius * 0.018))))
        painter.drawLine(int(cx), int(cy), int(nx), int(ny))

        painter.setBrush(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        r_hub = radius * 0.035
        painter.drawEllipse(int(cx - r_hub), int(cy - r_hub), int(r_hub * 2), int(r_hub * 2))

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#060709"))
        w, h = self.width(), self.height()

        # Resolve mode label and theme
        raw_mode = self.values.get("DriveModeSelect", "Eco")
        mode_val = getattr(raw_mode, "name", raw_mode)
        if isinstance(mode_val, int):
            mode = {0: "Eco", 1: "Sport", 2: "Track"}.get(mode_val, "Eco")
        else:
            mode = str(mode_val)

        accent = MODE_COLORS.get(mode, MODE_COLORS["Eco"])
        speed = float(self.values.get("VehicleSpeed", 0.0))
        rpm = float(self.values.get("EngineRPM", 800.0))
        gear = int(self.values.get("CurrentGear", 1))

        # Top banner separator
        painter.setPen(QPen(QColor("#161c22"), 1))
        painter.drawLine(36, 74, w - 36, 74)

        # Title
        self._draw_text(painter, w / 2, 43, "VISTEON  /  SIL COCKPIT", 17, QColor("#dce2e7"), QFont.Weight.DemiBold)

        # Drive mode badge
        bw, bh = 126, 28
        bx, by = w - 182, 22
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(int(bx), int(by), int(bw), int(bh), 8, 8)
        self._draw_text(painter, bx + bw / 2, 42, mode.upper(), 11, QColor("#060709"), QFont.Weight.Bold)

        # Main dials
        gr = min(w * 0.205, h * 0.34)
        gy = h * 0.48
        self._draw_gauge(painter, w * 0.25, gy, gr, speed, 300.0, "VEHICLE SPEED", "km/h", accent, 10)
        rpm_color = QColor("#ff5d66") if rpm > 7800 else accent
        self._draw_gauge(painter, w * 0.75, gy, gr, rpm, 9000.0, "ENGINE SPEED", "rpm", rpm_color, 9)

        # Center cluster: shift lights, gear readout, boost meter
        self._draw_shift_lights(painter, w / 2, h * 0.155, rpm, accent)
        self._draw_gear_box(painter, w / 2, gy, gear, accent)
        self._draw_boost_bar(painter, w / 2, h * 0.70, accent)
        self._draw_status_bar(painter, w, h, accent)
        painter.end()

    def _draw_shift_lights(self, painter: QPainter, cx: float, y: float, rpm: float, accent: QColor) -> None:
        active_count = min(12, max(0, math.ceil(min(rpm / 9000.0, 1.0) * 12)))
        spacing = 23
        for i in range(12):
            x = cx + (i - 5.5) * spacing
            active = i < active_count
            color = accent if i < 8 else QColor("#ff5d35")
            if rpm > 7800:
                color = QColor("#ff2638") if self._redline_flash else QColor("#3b151a")
                active = True
            elif not active:
                color = QColor("#20262c")

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(int(x - 7), int(y - 4), 14, 8, 4, 4)

    def _draw_gear_box(self, painter: QPainter, cx: float, cy: float, gear: int, accent: QColor) -> None:
        bw, bh = 92, 82
        x = int(cx - bw / 2)
        y = int(cy - bh / 2)

        painter.setPen(QPen(QColor("#29313a"), 1.5))
        painter.setBrush(QColor("#0c1014"))
        painter.drawRoundedRect(x, y, bw, bh, 12, 12)
        self._draw_text(painter, cx, y + 26, "GEAR", 10, QColor("#87929c"), QFont.Weight.DemiBold)
        self._draw_text(painter, cx, y + 69, str(gear), 36, accent, QFont.Weight.Bold)

    def _draw_boost_bar(self, painter: QPainter, cx: float, y: float, accent: QColor) -> None:
        boost = min(max(float(self.values.get("TurboBoostBar", 0.0)), 0.0), 3.0)
        bw = min(260.0, self.width() * 0.34)
        x = int(cx - bw / 2)

        self._draw_text(painter, cx, y - 7, f"BOOST   {boost:.2f} bar", 12, QColor("#b5bec6"), QFont.Weight.DemiBold)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b2229"))
        painter.drawRoundedRect(x, int(y), int(bw), 8, 4, 4)

        fill_w = int(bw * boost / 3.0)
        if fill_w > 0:
            painter.setBrush(accent)
            painter.drawRoundedRect(x, int(y), fill_w, 8, 4, 4)

    def _draw_status_bar(self, painter: QPainter, width: int, height: int, accent: QColor) -> None:
        coolant = float(self.values.get("CoolantTemperature", 22.0))
        fuel = float(self.values.get("FuelTankLevel", 100.0))
        oil = float(self.values.get("EngineOilPressure", 0.0))

        self._draw_text(painter, width * 0.20, height - 33, f"COOLANT  {coolant:.0f} C", 12, QColor("#b5bec6"))
        self._draw_text(painter, width * 0.50, height - 33, f"OIL  {oil:.1f} bar    FUEL  {fuel:.0f}%", 12, QColor("#b5bec6"))
        self._draw_text(painter, width * 0.81, height - 33, f"CAN  {self._fps} fps", 12, QColor("#b5bec6"))

        # DTC Alert or Interface Status
        raw_dtc = self.values.get("ActiveDTCAlert", 0)
        dtc_val = getattr(raw_dtc, "value", raw_dtc)
        if isinstance(dtc_val, (int, float)):
            has_alert = dtc_val != 0
        else:
            has_alert = str(raw_dtc).strip().lower() in ("1", "active", "true")

        banner_w = min(430.0, width * 0.60)
        banner_x = int((width - banner_w) / 2)
        banner_y = int(height - 90)

        if has_alert:
            painter.setPen(QPen(QColor("#7e252b"), 1))
            painter.setBrush(QColor("#321216"))
            painter.drawRoundedRect(banner_x, banner_y, int(banner_w), 38, 8, 8)
            self._draw_text(painter, width / 2, banner_y + 27, "⚠ DTC: P0117 (COOLANT OVERHEAT)", 14, QColor("#ff6b73"), QFont.Weight.Bold)
        else:
            painter.setPen(QPen(QColor("#20262c"), 1))
            painter.setBrush(QColor("#0b0e11"))
            painter.drawRoundedRect(banner_x, banner_y, int(banner_w), 38, 8, 8)
            status_color = accent if self._bus_status == "CAN ONLINE" else QColor("#89939d")
            self._draw_text(painter, width / 2, banner_y + 27, self._bus_status, 10, status_color, QFont.Weight.DemiBold)


class CockpitWindow(QMainWindow):
    def __init__(
        self,
        dbc_path: Path,
        simulate: bool = False,
        drive_mode: str = "Sport",
    ) -> None:
        super().__init__()
        self.setWindowTitle("Visteon SIL Cockpit Display")
        self.resize(1200, 760)
        self.setMinimumSize(820, 520)

        self.cockpit = CockpitWidget()
        self.setCentralWidget(self.cockpit)

        self.sim_thread: EmbeddedSimulatorThread | None = None
        if simulate:
            self.sim_thread = EmbeddedSimulatorThread(drive_mode, dbc_path, self)
            self.sim_thread.start()

        self.listener = CanListener(dbc_path, self)
        self.listener.frame_received.connect(self.cockpit.update_from_frame)
        self.listener.listener_error.connect(self._on_listener_error)
        self.listener.listener_ready.connect(lambda: self.cockpit.set_bus_status("CAN ONLINE"))
        self.listener.start()

    def _on_listener_error(self, message: str) -> None:
        self.cockpit.set_bus_status("CAN ERROR")
        log.error("CAN listener halted: %s", message)

    def closeEvent(self, event: Any) -> None:
        if self.sim_thread is not None:
            self.sim_thread.stop()
            self.sim_thread.wait(1500)
        self.listener.stop()
        if not self.listener.wait(1500):
            log.warning("Listener thread teardown timed out")
        event.accept()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Digital Instrument Cluster UI")
    parser.add_argument("--dbc", type=Path, default=DBC_PATH, help="Network DBC path")
    parser.add_argument("--sim", "--simulate", action="store_true", dest="simulate", help="Start background simulation")
    parser.add_argument("--drive-mode", choices=("Eco", "Sport", "Track"), default="Sport", help="Simulation drive mode")
    parser.add_argument("--fullscreen", action="store_true", help="Launch in fullscreen mode")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    app = QApplication(sys.argv)
    window = CockpitWindow(dbc_path=args.dbc, simulate=args.simulate, drive_mode=args.drive_mode)
    if args.fullscreen:
        window.showFullScreen()
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
