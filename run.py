#!/usr/bin/env python3
"""Launcher for the Visteon SIL Cockpit and ECU Simulator."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Visteon SIL Cockpit")
    parser.add_argument(
        "--mode",
        choices=("all", "display", "ecu"),
        default="all",
        help="Component to launch: 'all' (cockpit + ECU simulator), 'display' (cockpit only), 'ecu' (ECU simulator only). Default: all.",
    )
    parser.add_argument(
        "--drive-mode",
        choices=("Eco", "Sport", "Track"),
        default="Sport",
        help="Vehicle drive mode for simulation (default: Sport).",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Open cockpit in fullscreen mode.",
    )
    args = parser.parse_args()

    if args.mode == "ecu":
        from ecu_core import run_simulation

        run_simulation(drive_mode=args.drive_mode)
    elif args.mode == "display":
        import cockpit_display

        sys.argv = [sys.argv[0]]
        if args.fullscreen:
            sys.argv.append("--fullscreen")
        cockpit_display.main()
    else:  # 'all'
        import cockpit_display

        sys.argv = [sys.argv[0], "--sim", "--drive-mode", args.drive_mode]
        if args.fullscreen:
            sys.argv.append("--fullscreen")
        cockpit_display.main()


if __name__ == "__main__":
    main()
