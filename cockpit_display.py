#!/usr/bin/env python3
"""PyQt6 CAN cockpit display for the software-in-the-loop vehicle simulator."""

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

LOGGER = logging.getLogger("cockpit_display")
DBC_PATH = Path(__file__).with_name("automotive_network.dbc")
MODE_COLORS = {
    "Eco": QColor("#39d98a"),
    "Sport": QColor("#ffb547"),
    "Track": QColor("#ff4d5a"),
}
DEFAULT_VALUES: dict[str, Any] = {
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
    """Receive and decode CAN traffic away from the GUI event loop."""

    frame_received = pyqtSignal(dict)
    listener_error = pyqtSignal(str)
    listener_ready = pyqtSignal()

    def __init__(self, dbc_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dbc_path = dbc_path
        self._stop_requested = Event()

    def stop(self) -> None:
        self._stop_requested.set()

    def run(self) -> None:
        try:
            database = cantools.database.load_file(self._dbc_path)
            bus = create_bus()
        except (
            OSError,
            RuntimeError,
            can.CanError,
            ValueError,
            cantools.database.errors.Error,
        ) as exc:
            LOGGER.error("CAN listener could not start: %s", exc)
            self.listener_error.emit(str(exc))
            return

        self.listener_ready.emit()
        try:
            while not self._stop_requested.is_set():
                frame = bus.recv(timeout=0.1)
                if frame is None:
                    continue
                try:
                    message = database.get_message_by_frame_id(frame.arbitration_id)
                except KeyError:
                    continue
                try:
                    decoded = message.decode(frame.data, decode_choices=True)
                except (cantools.database.errors.DecodeError, ValueError) as exc:
                    LOGGER.warning(
                        "Could not decode CAN frame 0x%03X: %s",
                        frame.arbitration_id,
                        exc,
                    )
                    continue
                self.frame_received.emit(decoded)
        except (can.CanError, OSError) as exc:
            if not self._stop_requested.is_set():
                LOGGER.error("CAN receive failed: %s", exc)
                self.listener_error.emit(str(exc))
        finally:
            bus.shutdown()


class EmbeddedSimulatorThread(QThread):
    """Optional background thread running vehicle dynamics simulation."""

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

        LOGGER.info("Starting embedded vehicle simulation in %s mode.", self._drive_mode)
        try:
            run_simulation(
                drive_mode=self._drive_mode,
                dbc_path=self._dbc_path,
                stop_event=self._stop_event,
            )
        except Exception as exc:
            LOGGER.error("Embedded simulation error: %s", exc)


class CockpitWidget(QWidget):
    """Single-surface, antialiased cockpit rendering with live CAN metrics."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(820, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.values = DEFAULT_VALUES.copy()
        self._frame_times: deque[float] = deque()
        self._frames_per_second = 0
        self._listener_status = "CONNECTING TO CAN"
        self._flash_on = True
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_metrics)
        self._timer.start()

    def set_listener_status(self, message: str) -> None:
        self._listener_status = message
        self.update()

    def update_from_frame(self, decoded: dict[str, Any]) -> None:
        self.values.update(decoded)
        self._frame_times.append(time.monotonic())
        self.update()

    def _update_metrics(self) -> None:
        now = time.monotonic()
        while self._frame_times and now - self._frame_times[0] > 1.0:
            self._frame_times.popleft()
        self._frames_per_second = len(self._frame_times)
        if float(self.values.get("EngineRPM", 0.0)) > 7800.0:
            self._flash_on = not self._flash_on
        else:
            self._flash_on = True
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
    def _point_on_arc(
        cx: float, cy: float, radius: float, angle_degrees: float
    ) -> tuple[float, float]:
        angle = math.radians(angle_degrees)
        return cx + radius * math.cos(angle), cy + radius * math.sin(angle)

    def _draw_gauge(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        radius: float,
        value: float,
        maximum: float,
        label: str,
        unit: str,
        accent: QColor,
        divisions: int,
    ) -> None:
        progress = min(max(value / maximum, 0.0), 1.0)
        arc_radius = radius * 0.82
        track = QPainterPath()
        foreground = QPainterPath()
        points = max(80, divisions * 12)
        for index in range(points + 1):
            fraction = index / points
            x, y = self._point_on_arc(
                center_x, center_y, arc_radius, 135.0 + 270.0 * fraction
            )
            (foreground if fraction <= progress else track).moveTo(x, y)
            active_path = foreground if fraction <= progress else track
            if index > 0:
                previous_fraction = (index - 1) / points
                if (previous_fraction <= progress) == (fraction <= progress):
                    previous_x, previous_y = self._point_on_arc(
                        center_x,
                        center_y,
                        arc_radius,
                        135.0 + 270.0 * previous_fraction,
                    )
                    active_path.moveTo(previous_x, previous_y)
                    active_path.lineTo(x, y)

        painter.setPen(
            QPen(
                QColor("#1c2229"),
                max(7, int(radius * 0.055)),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawPath(track)
        painter.setPen(
            QPen(
                accent,
                max(7, int(radius * 0.055)),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawPath(foreground)

        painter.setPen(QPen(QColor("#68727d"), 1.5))
        for tick in range(divisions + 1):
            fraction = tick / divisions
            angle = 135.0 + 270.0 * fraction
            outer_x, outer_y = self._point_on_arc(
                center_x, center_y, radius * 0.72, angle
            )
            inner_x, inner_y = self._point_on_arc(
                center_x, center_y, radius * 0.66, angle
            )
            painter.drawLine(int(inner_x), int(inner_y), int(outer_x), int(outer_y))

        self._draw_text(
            painter,
            center_x,
            center_y - radius * 0.28,
            label,
            max(11, int(radius * 0.105)),
            QColor("#9ba5af"),
            QFont.Weight.DemiBold,
        )
        display_value = f"{value:.0f}"
        self._draw_text(
            painter,
            center_x,
            center_y + radius * 0.10,
            display_value,
            max(30, int(radius * 0.34)),
            QColor("#f2f5f7"),
            QFont.Weight.Bold,
        )
        self._draw_text(
            painter,
            center_x,
            center_y + radius * 0.32,
            unit,
            max(11, int(radius * 0.11)),
            QColor("#89939d"),
        )

        needle_x, needle_y = self._point_on_arc(
            center_x, center_y, radius * 0.61, 135.0 + 270.0 * progress
        )
        painter.setPen(QPen(QColor("#f5f7f8"), max(2, int(radius * 0.018))))
        painter.drawLine(int(center_x), int(center_y), int(needle_x), int(needle_y))
        painter.setBrush(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            int(center_x - radius * 0.035),
            int(center_y - radius * 0.035),
            int(radius * 0.07),
            int(radius * 0.07),
        )

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#060709"))
        width = self.width()
        height = self.height()

        raw_mode = self.values.get("DriveModeSelect", "Eco")
        mode_name = getattr(raw_mode, "name", raw_mode)
        if isinstance(mode_name, int):
            mode = {0: "Eco", 1: "Sport", 2: "Track"}.get(mode_name, "Eco")
        else:
            mode = str(mode_name)

        accent = MODE_COLORS.get(mode, MODE_COLORS["Eco"])
        speed = float(self.values.get("VehicleSpeed", 0.0))
        rpm = float(self.values.get("EngineRPM", 800.0))
        gear = int(self.values.get("CurrentGear", 1))

        # Top divider
        painter.setPen(QPen(QColor("#161c22"), 1))
        painter.drawLine(36, 74, width - 36, 74)

        # Header title
        self._draw_text(
            painter,
            width / 2,
            43,
            "VISTEON  /  SIL COCKPIT",
            17,
            QColor("#dce2e7"),
            QFont.Weight.DemiBold,
        )

        # Mode badge pill with solid accent background and dark bold text
        badge_x = width - 182
        badge_y = 22
        badge_w = 126
        badge_h = 28
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(int(badge_x), int(badge_y), int(badge_w), int(badge_h), 8, 8)
        self._draw_text(
            painter,
            badge_x + badge_w / 2,
            42,
            mode.upper(),
            11,
            QColor("#060709"),
            QFont.Weight.Bold,
        )

        # Gauges
        gauge_radius = min(width * 0.205, height * 0.34)
        gauge_y = height * 0.48
        left_x = width * 0.25
        right_x = width * 0.75
        self._draw_gauge(
            painter,
            left_x,
            gauge_y,
            gauge_radius,
            speed,
            300.0,
            "VEHICLE SPEED",
            "km/h",
            accent,
            10,
        )
        self._draw_gauge(
            painter,
            right_x,
            gauge_y,
            gauge_radius,
            rpm,
            9000.0,
            "ENGINE SPEED",
            "rpm",
            QColor("#ff5d66") if rpm > 7800 else accent,
            9,
        )

        self._draw_shift_lights(painter, width / 2, height * 0.155, rpm, accent)
        self._draw_gear_box(painter, width / 2, gauge_y, gear, accent)
        self._draw_boost_bar(painter, width / 2, height * 0.70, accent)
        self._draw_status(painter, width, height, accent)
        painter.end()

    def _draw_shift_lights(
        self, painter: QPainter, center_x: float, y: float, rpm: float, accent: QColor
    ) -> None:
        active_count = min(12, max(0, math.ceil(min(rpm / 9000.0, 1.0) * 12)))
        spacing = 23
        for index in range(12):
            x = center_x + (index - 5.5) * spacing
            active = index < active_count
            color = accent if index < 8 else QColor("#ff5d35")
            if rpm > 7800:
                color = QColor("#ff2638") if self._flash_on else QColor("#3b151a")
                active = True
            elif not active:
                color = QColor("#20262c")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(int(x - 7), int(y - 4), 14, 8, 4, 4)

    def _draw_gear_box(
        self, painter: QPainter, center_x: float, center_y: float, gear: int, accent: QColor
    ) -> None:
        box_width, box_height = 92, 82
        x = int(center_x - box_width / 2)
        y = int(center_y - box_height / 2)
        painter.setPen(QPen(QColor("#29313a"), 1.5))
        painter.setBrush(QColor("#0c1014"))
        painter.drawRoundedRect(x, y, box_width, box_height, 12, 12)
        self._draw_text(
            painter,
            center_x,
            y + 26,
            "GEAR",
            10,
            QColor("#87929c"),
            QFont.Weight.DemiBold,
        )
        self._draw_text(
            painter,
            center_x,
            y + 69,
            str(gear),
            36,
            accent,
            QFont.Weight.Bold,
        )

    def _draw_boost_bar(
        self, painter: QPainter, center_x: float, y: float, accent: QColor
    ) -> None:
        boost = min(max(float(self.values.get("TurboBoostBar", 0.0)), 0.0), 3.0)
        bar_width = min(260.0, self.width() * 0.34)
        x = int(center_x - bar_width / 2)
        self._draw_text(
            painter,
            center_x,
            y - 7,
            f"BOOST   {boost:.2f} bar",
            12,
            QColor("#b5bec6"),
            QFont.Weight.DemiBold,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b2229"))
        painter.drawRoundedRect(x, int(y), int(bar_width), 8, 4, 4)
        fill_width = int(bar_width * boost / 3.0)
        if fill_width > 0:
            painter.setBrush(accent)
            painter.drawRoundedRect(x, int(y), fill_width, 8, 4, 4)

    def _draw_status(
        self, painter: QPainter, width: int, height: int, accent: QColor
    ) -> None:
        coolant = float(self.values.get("CoolantTemperature", 22.0))
        fuel = float(self.values.get("FuelTankLevel", 100.0))
        oil = float(self.values.get("EngineOilPressure", 0.0))
        self._draw_text(
            painter,
            width * 0.20,
            height - 33,
            f"COOLANT  {coolant:.0f} C",
            12,
            QColor("#b5bec6"),
        )
        self._draw_text(
            painter,
            width * 0.50,
            height - 33,
            f"OIL  {oil:.1f} bar    FUEL  {fuel:.0f}%",
            12,
            QColor("#b5bec6"),
        )
        self._draw_text(
            painter,
            width * 0.81,
            height - 33,
            f"CAN  {self._frames_per_second} fps",
            12,
            QColor("#b5bec6"),
        )

        raw_alert = self.values.get("ActiveDTCAlert", 0)
        alert_val = getattr(raw_alert, "value", raw_alert)
        if isinstance(alert_val, (int, float)):
            alert_active = alert_val != 0
        else:
            alert_active = str(raw_alert).strip().lower() in ("1", "active", "true")

        banner_width = min(430.0, width * 0.60)
        banner_x = (width - banner_width) / 2
        banner_y = height - 90
        if alert_active:
            painter.setPen(QPen(QColor("#7e252b"), 1))
            painter.setBrush(QColor("#321216"))
            painter.drawRoundedRect(
                int(banner_x), int(banner_y), int(banner_width), 38, 8, 8
            )
            self._draw_text(
                painter,
                width / 2,
                banner_y + 27,
                "⚠ DTC: P0117 (OVERHEAT)",
                14,
                QColor("#ff6b73"),
                QFont.Weight.Bold,
            )
        else:
            painter.setPen(QPen(QColor("#20262c"), 1))
            painter.setBrush(QColor("#0b0e11"))
            painter.drawRoundedRect(
                int(banner_x), int(banner_y), int(banner_width), 38, 8, 8
            )
            self._draw_text(
                painter,
                width / 2,
                banner_y + 27,
                self._listener_status,
                10,
                accent if self._listener_status == "CAN ONLINE" else QColor("#89939d"),
                QFont.Weight.DemiBold,
            )


class CockpitWindow(QMainWindow):
    def __init__(
        self,
        dbc_path: Path,
        simulate: bool = False,
        drive_mode: str = "Sport",
    ) -> None:
        super().__init__()
        self.setWindowTitle("Visteon SIL Cockpit")
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
        self.listener.listener_ready.connect(
            lambda: self.cockpit.set_listener_status("CAN ONLINE")
        )
        self.listener.start()

    def _on_listener_error(self, message: str) -> None:
        self.cockpit.set_listener_status("CAN ERROR")
        LOGGER.error("Cockpit CAN listener stopped: %s", message)

    def closeEvent(self, event: Any) -> None:
        if self.sim_thread is not None:
            self.sim_thread.stop()
            self.sim_thread.wait(1500)
        self.listener.stop()
        if not self.listener.wait(1500):
            LOGGER.warning("CAN listener did not stop within 1.5 seconds.")
        event.accept()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dbc",
        type=Path,
        default=DBC_PATH,
        help="DBC file to load (default: automotive_network.dbc beside this script).",
    )
    parser.add_argument(
        "--simulate",
        "--sim",
        action="store_true",
        dest="simulate",
        help="Run integrated ECU simulation alongside cockpit display.",
    )
    parser.add_argument(
        "--drive-mode",
        choices=("Eco", "Sport", "Track"),
        default="Sport",
        help="Simulated drive mode when running with --simulate (default: Sport).",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Launch window in fullscreen mode.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    window = CockpitWindow(
        dbc_path=args.dbc,
        simulate=args.simulate,
        drive_mode=args.drive_mode,
    )
    if args.fullscreen:
        window.showFullScreen()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
