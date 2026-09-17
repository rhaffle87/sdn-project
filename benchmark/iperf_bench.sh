#!/usr/bin/env bash
# ==============================================================================
# Throughput Benchmark Script using iperf3
# Measures data plane throughput across client-to-backend transit paths.
# ==============================================================================

set -e

VIP="${1:-10.0.0.100}"
PORT="${2:-80}"
DURATION="${3:-10}"
PARALLEL="${4:-2}"

echo "=== [SDN Project] Running iperf3 Data Plane Throughput Benchmark ==="
echo "[*] Target: ${VIP}:${PORT} | Duration: ${DURATION}s | Streams: ${PARALLEL}"
echo "[*] Note: The SDN controller load balances TCP port 80 (config.SERVICE_PORT)."
echo "[*]       Ensure an iperf3 server is active on the backend: 's1_srv iperf3 -s -p 80 &'"

if command -v iperf3 >/dev/null 2>&1; then
    iperf3 -c "${VIP}" -p "${PORT}" -t "${DURATION}" -P "${PARALLEL}" --json || {
        echo "[!] iperf3 client execution failed or target server not listening on port ${PORT}."
        echo "[*] Note: Ensure 'iperf3 -s -p ${PORT}' is running on the backend server in Mininet."
    }
else
    echo "[!] iperf3 is not installed. Please install via: sudo apt-get install iperf3"
    exit 1
fi

