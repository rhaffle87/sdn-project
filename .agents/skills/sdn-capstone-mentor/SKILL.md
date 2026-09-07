---
name: sdn-capstone-mentor
description: "Technical mentor for SDN Capstone project at ITS. Guides Mininet topology simulation, Ryu controller development, OVS flow table inspection, traffic benchmarking, and troubleshooting for the SDN Load Balancer and Traffic Engineering system."
---

# SDN Capstone Mentor Skill: Load Balancer & Traffic Engineering

## Overview
This skill provides automated workflows, command runbooks, and debugging procedures for the SDN Load Balancer and Traffic Engineering capstone project.

---

## 1. Environment Verification & Hygiene

Before running any simulation or test in WSL2:

```bash
# 1. Clean up stale Mininet topologies, open sockets, and OVS bridges
sudo mn -c

# 2. Verify Open vSwitch daemon is running
sudo systemctl status openvswitch-switch

# 3. Check Python and Ryu environment in WSL
/home/rafli_alif/sdn-venv/bin/python3 -c "import ryu, mininet, scapy, flask; print('Core SDN stack ready!')"
```

---

## 2. Common Workflows & Runbooks

### Workflow A: Launching Ryu Controller
Run the modular Ryu controller with OpenFlow 1.3:

```bash
/home/rafli_alif/sdn-venv/bin/ryu-manager --verbose controller/main.py --ofp-tcp-listen-port 6653
```

### Workflow B: Launching the Mininet Topology
In a separate terminal or background session:

```bash
sudo /home/rafli_alif/sdn-venv/bin/python3 topology/lb_topology.py
```

### Workflow C: Starting Flask Backend Servers
When inside the Mininet CLI or launched via Mininet script:

```bash
mininet> s1_srv /home/rafli_alif/sdn-venv/bin/python3 server/backend_server.py --id srv1 --port 80 &
mininet> s2_srv /home/rafli_alif/sdn-venv/bin/python3 server/backend_server.py --id srv2 --port 80 &
mininet> s3_srv /home/rafli_alif/sdn-venv/bin/python3 server/backend_server.py --id srv3 --port 80 &
mininet> s4_srv /home/rafli_alif/sdn-venv/bin/python3 server/backend_server.py --id srv4 --port 80 &
```

### Workflow D: Inspecting OVS Flow Tables
Inspect the installed NAT rewrite rules and priority table:

```bash
# Dump flows for ingress switch s1
sudo ovs-ofctl -O OpenFlow13 dump-flows s1

# Dump port stats to inspect byte counters and utilization
sudo ovs-ofctl -O OpenFlow13 dump-ports s1
```

### Workflow E: Automated Testing & Benchmarking
Run non-interactive verification and benchmarking:

```bash
# 1. Verify VIP rewrite
sudo /home/rafli_alif/sdn-venv/bin/python3 tests/test_vip_rewrite.py

# 2. Verify LB algorithms (Round-Robin, Least-Connections, Weighted)
sudo /home/rafli_alif/sdn-venv/bin/python3 tests/test_lb_algorithms.py

# 3. Test failover on backend crash and link disruption
sudo /home/rafli_alif/sdn-venv/bin/python3 tests/test_failover.py

# 4. Run comprehensive benchmark suite
sudo /home/rafli_alif/sdn-venv/bin/python3 benchmark/run_all_benchmarks.py
```

---

## 3. Troubleshooting & Failure Recovery

### Problem 1: VIP ARP Resolution Fails
- **Symptom:** `curl http://10.0.0.100` hangs or reports `Destination Host Unreachable`.
- **Cause:** Controller not intercepting ARP requests for VIP `10.0.0.100` or ARP reply packet is dropped.
- **Fix:** Verify controller ARP responder flow (`priority=30`) or Packet-In ARP handling in `load_balancer.py`. Inspect with `sudo tcpdump -i s1-eth1 -n -e`.

### Problem 2: TCP Handshake Fails / Connection Reset
- **Symptom:** Client sends SYN to VIP, backend receives rewritten SYN, but client receives SYN-ACK with backend's real IP instead of VIP.
- **Cause:** Missing reverse NAT flow (`priority=40`) rewriting `ipv4_src=VIP` and `eth_src=VIP_MAC` on traffic from backend to client.
- **Fix:** Ensure bidirectional flow installation in `flow_manager.py` when the first Packet-In is processed.

### Problem 3: Port Stats Polling Not Updating
- **Symptom:** Utilization stays 0 Mbps despite active traffic.
- **Cause:** Blocking calls inside stats monitor loop stalling eventlet greenlet.
- **Fix:** Always use `hub.sleep()` and verify `OFPPortStatsRequest` multipart replies are handled by `EventOFPPortStatsReply`.
