#!/usr/bin/env bash
# ==============================================================================
# Throughput Benchmark Script using iperf3
# Measures data plane throughput across client-to-backend transit paths.
# ==============================================================================

set -e

VIP="${1:-10.0.0.100}"
PORT="${2:-5201}"
DURATION="${3:-10}"
PARALLEL="${4:-2}"

echo "=== [SDN Project] Running iperf3 Data Plane Throughput Benchmark ==="
echo "[*] Target: ${VIP}:${PORT} | Duration: ${DURATION}s | Streams: ${PARALLEL}"

if command -v iperf3 >/dev/null 2>&1; then
    iperf3 -c "${VIP}" -p "${PORT}" -t "${DURATION}" -P "${PARALLEL}" --json || {
        echo "[!] iperf3 client execution failed or target server not listening on port ${PORT}."
        echo "[*] Note: Ensure iperf3 -s is running on the target backend in Mininet."
    }
else
    echo "[!] iperf3 is not installed. Please install via: sudo apt-get install iperf3"
    exit 1
fi

