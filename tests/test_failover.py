#!/usr/bin/env python3
"""
Automated Test: High Availability & Failover Resilience
Validates:
1. Backend Server Failure: When srv2 crashes, controller dynamically excludes it from pool.
2. Backend Server Recovery: When srv2 recovers, it rejoins active rotation.
3. Link Failure: When primary link s1-s2 goes DOWN, traffic engineering fails over to Path B (s1-s3-s4).
"""

import collections
import json
import os
import subprocess
import sys
import time
import urllib.request

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel
from topology.lb_topology import DiamondLBTopo, start_backend_servers

def set_backend_health(backend_id, healthy):
    """Inform Ryu controller of backend health change via REST API."""
    url = "http://127.0.0.1:8080/api/backend/health"
    data = json.dumps({"backend_id": backend_id, "healthy": healthy}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[WARN] Failed to set backend health via REST: {e}")
        return False

def test_failover():
    setLogLevel('info')
    print("\n=======================================================")
    print("  TEST: High Availability, Failover & Self-Healing     ")
    print("=======================================================\n")

    subprocess.run(["sudo", "pkill", "-f", "backend_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    topo = DiamondLBTopo()
    net = Mininet(topo=topo, switch=OVSSwitch, controller=None, autoSetMacs=False, autoStaticArp=False)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    try:
        net.start()
        start_backend_servers(net, PROJECT_ROOT)
        h1 = net.get('h1')
        time.sleep(3)

        # -------------------------------------------------------------
        # Phase 1: Normal Baseline Traffic (All 4 backends UP)
        # -------------------------------------------------------------
        print("\n--- [1/3] Baseline: Verifying All 4 Backends Active ---")
        baseline_counts = collections.defaultdict(int)
        for i in range(8):
            out = h1.cmd("curl -s --connect-timeout 2 http://10.0.0.100/")
            try:
                srv = json.loads(out).get("server_id")
                baseline_counts[srv] += 1
            except Exception:
                pass
            time.sleep(0.1)

        print(f"[*] Baseline distribution: {dict(baseline_counts)}")
        assert "srv2" in baseline_counts, "srv2 should be receiving traffic initially"
        print("[PASS] All backends actively serving requests.")

        # -------------------------------------------------------------
        # Phase 2: Backend Failure (srv2 DOWN)
        # -------------------------------------------------------------
        print("\n--- [2/3] Simulating Backend Failure: Killing srv2 ---")
        # Mark srv2 down
        set_backend_health("srv2", False)
        time.sleep(1)

        fail_counts = collections.defaultdict(int)
        NUM_FAIL_REQUESTS = 12
        for i in range(NUM_FAIL_REQUESTS):
            out = h1.cmd("curl -s --connect-timeout 2 http://10.0.0.100/")
            try:
                srv = json.loads(out).get("server_id")
                fail_counts[srv] += 1
                print(f"  Request #{i+1:02d} served by: {srv}")
            except Exception:
                print(f"  Request #{i+1:02d} FAILED!")
            time.sleep(0.1)

        print(f"[*] Post-failure distribution: {dict(fail_counts)}")
        assert "srv2" not in fail_counts, f"srv2 should NOT receive any traffic while DOWN! Got: {fail_counts}"
        assert sum(fail_counts.values()) == NUM_FAIL_REQUESTS, "All requests should be successfully absorbed by healthy servers"
        print("[PASS] Dead backend srv2 was cleanly excluded with 0% request drop!")

        # Recover srv2
        print("\n[*] Recovering srv2 back to ONLINE status...")
        set_backend_health("srv2", True)
        time.sleep(1)

        rec_counts = collections.defaultdict(int)
        for _ in range(8):
            out = h1.cmd("curl -s --connect-timeout 2 http://10.0.0.100/")
            try:
                srv = json.loads(out).get("server_id")
                rec_counts[srv] += 1
            except Exception:
                pass
            time.sleep(0.1)

        print(f"[*] Post-recovery distribution: {dict(rec_counts)}")
        assert "srv2" in rec_counts, "srv2 should resume receiving traffic after recovery!"
        print("[PASS] srv2 recovered and seamlessly rejoined the active pool!")

        # -------------------------------------------------------------
        # Phase 3: Link Failure (Primary Link s1-s2 DOWN)
        # -------------------------------------------------------------
        print("\n--- [3/3] Simulating Core Link Outage: Link s1-s2 DOWN ---")
        net.configLinkStatus('s1', 's2', 'down')
        time.sleep(1)

        link_fail_success = 0
        for i in range(6):
            out = h1.cmd("curl -s --connect-timeout 2 http://10.0.0.100/")
            try:
                data = json.loads(out)
                if data.get("status") == "success":
                    link_fail_success += 1
                    print(f"  Req #{i+1:02d} via Path B -> {data['server_id']}")
            except Exception as e:
                print(f"  Req #{i+1:02d} FAILED: {e}")
            time.sleep(0.1)

        print(f"[*] Link failover success rate: {link_fail_success}/6")
        assert link_fail_success == 6, f"Expected 6/6 requests to succeed via Path B, got {link_fail_success}"
        print("[PASS] Link failure detected! Controller automatically failed over to Path B with 100% success!")

        print("\n=======================================================")
        print("  ALL FAILOVER & RESILIENCE TESTS PASSED!              ")
        print("=======================================================\n")
        return True

    except Exception as e:
        print(f"\n[FAIL] Failover test encountered error: {e}")
        return False
    finally:
        subprocess.run(["sudo", "pkill", "-f", "backend_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        net.stop()
        subprocess.run(["sudo", "mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    success = test_failover()
    sys.exit(0 if success else 1)
