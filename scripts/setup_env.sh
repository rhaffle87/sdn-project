#!/usr/bin/env bash
set -e

echo "=== [SDN Project] Checking Environment Dependencies ==="

# 1. Check Python virtual environment
VENV_PATH="${VENV_PATH:-$HOME/sdn-venv}"
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
fi

# 2. Check system utilities
echo "Checking system utilities..."
command -v mn >/dev/null 2>&1 || { echo "Mininet not found. Install with: sudo apt install mininet"; exit 1; }
command -v ovs-vsctl >/dev/null 2>&1 || { echo "Open vSwitch not found. Install with: sudo apt install openvswitch-switch"; exit 1; }
command -v iperf3 >/dev/null 2>&1 || { echo "iperf3 not found. Install with: sudo apt install iperf3"; exit 1; }

# 3. Ensure Open vSwitch service is running
sudo service openvswitch-switch status >/dev/null 2>&1 || {
    echo "Starting openvswitch-switch service..."
    sudo service openvswitch-switch start
}

# 4. Patch Mininet clean.py to prevent 'sudo mn -c' from killing ryu-manager
MININET_CLEAN_PY="/usr/lib/python3/dist-packages/mininet/clean.py"
if [ -f "$MININET_CLEAN_PY" ] && grep -q "'ryu-manager'" "$MININET_CLEAN_PY" 2>/dev/null; then
    echo "Patching Mininet clean.py to protect ryu-manager from 'mn -c' auto-termination..."
    sudo sed -i "s/'ryu-manager'//g" "$MININET_CLEAN_PY"
fi

# 5. Install / verify Python requirements
echo "Verifying Python dependencies in $VENV_PATH..."
"$VENV_PATH/bin/pip" install --quiet -r requirements.txt

# 5. Smoke test imports
"$VENV_PATH/bin/python3" -c "
import ryu
import mininet
import scapy
import flask
import matplotlib
import networkx
print('All core libraries (ryu, mininet, scapy, flask, matplotlib, networkx) successfully imported!')
"

echo "=== [SDN Project] Environment Ready ==="
