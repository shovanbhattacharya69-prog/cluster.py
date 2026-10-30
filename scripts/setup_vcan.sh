#!/usr/bin/env bash
# Sets up a Linux virtual CAN network interface (vcan0) for SIL testing.
set -euo pipefail

INTERFACE="vcan0"

echo "[INFO] Loading Linux vcan kernel module..."
sudo modprobe vcan

if ip link show "$INTERFACE" &> /dev/null; then
    echo "[INFO] Interface $INTERFACE already exists. Bringing it up..."
    sudo ip link set up "$INTERFACE"
else
    echo "[INFO] Creating virtual CAN interface: $INTERFACE..."
    sudo ip link add dev "$INTERFACE" type vcan
    sudo ip link set up "$INTERFACE"
fi

echo "[SUCCESS] $INTERFACE is online and ready for CAN traffic."
ip -details link show "$INTERFACE"
