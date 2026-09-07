#!/usr/bin/env bash
set -e

TEST_SCRIPT="$1"
if [ -z "$TEST_SCRIPT" ]; then
    echo "Usage: ./scripts/run_test.sh <path_to_test.py>"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 1. Clean up any stale state
./scripts/cleanup.sh

# 2. Start Ryu controller in background
echo "[*] Starting Ryu controller (OpenFlow 1.3 on port 6653)..."
/home/rafli_alif/sdn-venv/bin/ryu-manager controller/main.py --ofp-tcp-listen-port 6653 > /tmp/ryu.log 2>&1 &
RYU_PID=$!

# Wait for controller port 6653 to be ready
echo "[*] Waiting for controller to listen on port 6653..."
python3 -c "
import socket, time, sys
for _ in range(30):
    try:
        s = socket.create_connection(('127.0.0.1', 6653), timeout=1)
        s.close()
        print('Controller is ready on port 6653!')
        sys.exit(0)
    except Exception:
        time.sleep(0.5)
print('Error: Timed out waiting for Ryu on port 6653')
sys.exit(1)
"

# 3. Run the test
echo "[*] Executing test script: $TEST_SCRIPT..."
EXIT_CODE=0
sudo /home/rafli_alif/sdn-venv/bin/python3 "$TEST_SCRIPT" || EXIT_CODE=$?

# 4. Stop controller and clean up
echo "[*] Stopping Ryu controller (PID: $RYU_PID)..."
sudo kill -9 "$RYU_PID" 2>/dev/null || true
./scripts/cleanup.sh

if [ $EXIT_CODE -ne 0 ]; then
    echo "[-] Test failed! Dumping controller log (/tmp/ryu.log):"
    cat /tmp/ryu.log
fi

exit $EXIT_CODE
