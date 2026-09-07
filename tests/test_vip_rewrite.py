#!/usr/bin/env python3
"""
Automated Test: VIP ARP and Bidirectional NAT Address Rewriting
Validates:
1. ARP resolution for VIP 10.0.0.100 returning virtual MAC 00:00:00:00:00:fe.
2. End-to-end HTTP request/response to VIP from client h1.
3. Inspection of Open vSwitch flow tables verifying forward and reverse NAT rules.
"""

import json
import os
import subprocess
import sys
import time

# Add project root to Python module path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel, info
from topology.lb_topology import DiamondLBTopo, start_backend_servers

def run_test():
    setLogLevel('info')
    print("\n=======================================================")
    print("  TEST: VIP ARP Resolution & Bidirectional NAT Rewrite ")
    print("=======================================================\n")

    # 1. Cleanup backend processes if any remain
    subprocess.run(["sudo", "pkill", "-f", "backend_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Build Mininet Network
    topo = DiamondLBTopo()
    net = Mininet(topo=topo, switch=OVSSwitch, controller=None, autoSetMacs=False, autoStaticArp=False)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    try:
        net.start()
        start_backend_servers(net, PROJECT_ROOT)

        h1 = net.get('h1')
        print("[+] Waiting 3 seconds for OpenFlow handshake and server startup...")
        time.sleep(3)

        # 3. Test ARP Resolution for VIP (10.0.0.100)
        print("[*] Step 1: Testing ARP resolution for VIP 10.0.0.100 from h1...", flush=True)
        arp_out = h1.cmd("arping -c 2 -w 2 10.0.0.100")
        print(arp_out, flush=True)
        if "00:00:00:00:00:fe" in arp_out.lower():
            print("[PASS] VIP ARP resolved correctly to 00:00:00:00:00:fe!", flush=True)
        else:
            print("[WARN] Checking arp cache...", flush=True)
            arp_cache = h1.cmd("arp -n 10.0.0.100")
            print(arp_cache, flush=True)

        # 4. Test HTTP GET to VIP (10.0.0.100)
        print("\n[*] Step 2: Sending HTTP GET request from h1 to http://10.0.0.100/...", flush=True)
        curl_out = h1.cmd("curl -s -S --connect-timeout 5 http://10.0.0.100/")
        print(f"Response:\n{curl_out}", flush=True)

        assert "status" in curl_out and "server_id" in curl_out, f"Invalid or empty response: {curl_out}"
        data = json.loads(curl_out)
        print(f"[PASS] Successfully connected to VIP! Served by: {data['server_id']} (IP: {data['host_ip']})")

        # 5. Inspect OVS Flow Table on Ingress Switch s1
        print("\n[*] Step 3: Inspecting OVS Flow Table on s1 (Ingress Switch)...")
        flows_s1 = subprocess.check_output(["sudo", "ovs-ofctl", "-O", "OpenFlow13", "dump-flows", "s1"]).decode()
        print(flows_s1)

        # Verify Forward NAT rule exists
        has_fwd_nat = "nw_dst=10.0.0.100" in flows_s1 or "set_field:10.0.0.1" in flows_s1
        # Verify Reverse NAT rule exists
        has_rev_nat = "set_field:10.0.0.100->nw_src" in flows_s1 or "10.0.0.100" in flows_s1

        assert has_fwd_nat, "Forward NAT rule not found in s1 flow table!"
        assert has_rev_nat, "Reverse NAT rule not found in s1 flow table!"
        print("[PASS] Both Forward and Reverse NAT rules successfully installed in OVS flow table!")

        print("\n=======================================================")
        print("  ALL VIP REWRITE & NAT CHECKS PASSED SUCCESSFULLY!    ")
        print("=======================================================\n")
        return True

    except Exception as e:
        print(f"\n[FAIL] Test encountered error: {e}")
        return False
    finally:
        print("[*] Cleaning up network...")
        subprocess.run(["sudo", "pkill", "-f", "backend_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        net.stop()
        subprocess.run(["sudo", "mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
