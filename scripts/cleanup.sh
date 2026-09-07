#!/usr/bin/env bash

echo "=== [SDN Project] Cleaning up Mininet, OVS, and Background Processes ==="

# 1. Clean Mininet state
sudo mn -c 2>/dev/null || true

# 2. Terminate background controller, server, or dashboard instances
sudo pkill -f "ryu-manager" 2>/dev/null || true
sudo pkill -f "backend_server.py" 2>/dev/null || true
sudo pkill -f "live_dashboard.py" 2>/dev/null || true
sudo pkill -f "iperf3" 2>/dev/null || true

# 3. Clean OVS bridges if any remain
for br in $(sudo ovs-vsctl list-br 2>/dev/null); do
    echo "Removing dangling bridge $br..."
    sudo ovs-vsctl del-br "$br" 2>/dev/null || true
done

echo "=== [SDN Project] Cleanup Complete ==="
