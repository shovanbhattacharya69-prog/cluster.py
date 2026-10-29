#!/usr/bin/env python3
"""
Application launcher for the cockpit cluster and ECU simulator.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Visteon SIL Cockpit Launcher")
    parser.add_argument(
        "--mode",
        choices=("all", "cluster", "ecu"),
        default="all",
        help="Target subsystem: 'all' (cluster + embedded ECU), 'cluster' (display only), 'ecu' (ECU only). Default: all",
    )
    parser.add_argument(
        "--drive-mode",
        choices=("Eco", "Sport", "Track"),
        default="Sport",
        help="Initial driving profile (default: Sport)",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Run display in full-screen mode",
    )
    args = parser.parse_args()

    if args.mode == "ecu":
        from ecu_core import run_simulation

        run_simulation(drive_mode=args.drive_mode)
    elif args.mode == "cluster":
        import cockpit_display

        sys.argv = [sys.argv[0]]
        if args.fullscreen:
            sys.argv.append("--fullscreen")
        cockpit_display.main()
    else:
        import cockpit_display

        sys.argv = [sys.argv[0], "--sim", "--drive-mode", args.drive_mode]
        if args.fullscreen:
            sys.argv.append("--fullscreen")
        cockpit_display.main()


if __name__ == "__main__":
    main()
