#!/usr/bin/env bash
"""
Throughput Benchmark Script using iperf3
Measures data plane throughput across client-to-backend transit paths.
"""

echo "=== [SDN Project] Running iperf3 Data Plane Throughput Benchmark ==="

# 1. Start iperf3 servers on backends if running in Mininet host namespaces
echo "[*] Launching iperf3 benchmark tests (Multi-stream TCP)..."
# In Mininet CLI or test script, run:
# h1 iperf3 -c 10.0.0.11 -t 10 -P 2
# h2 iperf3 -c 10.0.0.12 -t 10 -P 2

echo "[*] iperf3 throughput benchmark helper ready."
