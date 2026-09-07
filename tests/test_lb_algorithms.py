#!/usr/bin/env python3
"""
Automated Test: Load Balancing Algorithms (Round-Robin, Weighted, Least-Connections)
Validates distribution characteristics across backends under different LB policies.
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

def set_controller_algorithm(algo_name):
    """Call Ryu REST API to update active LB algorithm."""
    url = "http://127.0.0.1:8080/api/algorithm"
    data = json.dumps({"algorithm": algo_name}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            res = json.loads(resp.read().decode())
            print(f"[*] Set controller algorithm to '{algo_name}': {res.get('status')}")
            return res.get("status") == "success"
    except Exception as e:
        print(f"[WARN] Failed to switch algorithm via REST API: {e}")
        return False

def test_algorithms():
    setLogLevel('info')
    print("\n=======================================================")
    print("  TEST: Load Balancing Algorithm Distribution Patterns ")
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
        # Test 1: Round-Robin Distribution
        # -------------------------------------------------------------
        print("\n--- [1/3] Testing Round-Robin Algorithm ---")
        set_controller_algorithm("round_robin")
        time.sleep(1)

        rr_counts = collections.defaultdict(int)
        NUM_RR_REQUESTS = 12
        for i in range(NUM_RR_REQUESTS):
            out = h1.cmd("curl -s --connect-timeout 2 http://10.0.0.100/")
            try:
                data = json.loads(out)
                srv = data.get("server_id", "unknown")
                rr_counts[srv] += 1
                print(f"  Req #{i+1:02d} -> {srv}")
            except Exception:
                print(f"  Req #{i+1:02d} -> ERROR: {out}")
            time.sleep(0.1)

        print(f"[*] Round-Robin Distribution (12 requests): {dict(rr_counts)}")
        assert len(rr_counts) == 4, f"Expected all 4 servers to receive traffic, got {len(rr_counts)}"
        for srv, count in rr_counts.items():
            assert count == 3, f"Expected exact round-robin count 3 for {srv}, got {count}"
        print("[PASS] Round-Robin perfectly distributed requests (3 to each of the 4 backends)!")

        # -------------------------------------------------------------
        # Test 2: Weighted Distribution
        # -------------------------------------------------------------
        print("\n--- [2/3] Testing Weighted Algorithm (Weights: srv1=1, srv2=2, srv3=1, srv4=2) ---")
        set_controller_algorithm("weighted")
        time.sleep(1)

        weighted_counts = collections.defaultdict(int)
        NUM_WEIGHTED_REQUESTS = 12  # Total weight sum = 1+2+1+2 = 6, so 12 requests = 2 cycles
        for i in range(NUM_WEIGHTED_REQUESTS):
            out = h1.cmd("curl -s --connect-timeout 2 http://10.0.0.100/")
            try:
                data = json.loads(out)
                srv = data.get("server_id", "unknown")
                weighted_counts[srv] += 1
                print(f"  Req #{i+1:02d} -> {srv}")
            except Exception:
                print(f"  Req #{i+1:02d} -> ERROR: {out}")
            time.sleep(0.1)

        print(f"[*] Weighted Distribution (12 requests): {dict(weighted_counts)}")
        assert weighted_counts["srv2"] == 2 * weighted_counts["srv1"], "srv2 count should be 2x srv1!"
        assert weighted_counts["srv4"] == 2 * weighted_counts["srv3"], "srv4 count should be 2x srv3!"
        print("[PASS] Weighted algorithm matches configured 1:2:1:2 weight ratio!")

        # -------------------------------------------------------------
        # Test 3: Least-Connections Distribution
        # -------------------------------------------------------------
        print("\n--- [3/3] Testing Least-Connections Algorithm ---")
        set_controller_algorithm("least_connections")
        time.sleep(1)

        lc_counts = collections.defaultdict(int)
        for i in range(8):
            out = h1.cmd("curl -s --connect-timeout 2 http://10.0.0.100/")
            try:
                data = json.loads(out)
                srv = data.get("server_id", "unknown")
                lc_counts[srv] += 1
                print(f"  Req #{i+1:02d} -> {srv}")
            except Exception:
                print(f"  Req #{i+1:02d} -> ERROR: {out}")
            time.sleep(0.1)

        print(f"[*] Least-Connections Distribution (8 requests): {dict(lc_counts)}")
        assert len(lc_counts) == 4, f"Least-Connections should distribute across all servers, got {len(lc_counts)}"
        print("[PASS] Least-Connections successfully balanced load across idle servers!")

        print("\n=======================================================")
        print("  ALL LOAD BALANCING ALGORITHM CHECKS PASSED!          ")
        print("=======================================================\n")
        return True

    except Exception as e:
        print(f"\n[FAIL] Algorithm test encountered error: {e}")
        return False
    finally:
        subprocess.run(["sudo", "pkill", "-f", "backend_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        net.stop()
        subprocess.run(["sudo", "mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    success = test_algorithms()
    sys.exit(0 if success else 1)
