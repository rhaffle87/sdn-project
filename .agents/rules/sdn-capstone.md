# SDN Capstone Project: Architecture & Development Rules

These rules apply to all code, configuration, scripts, and documentation generated within this workspace.

---

## 1. OpenFlow 1.3 Protocol Standards
- **Version Enforcement:** Must strictly use OpenFlow 1.3 (`OFP_VERSION = 0x04`).
- **Switch Handshake Protocol:**
  - On switch connection (`EventOFPSwitchFeatures`), the controller must immediately install a **Table-Miss flow entry** (match: empty, priority: 0, actions: `[OFPActionOutput(OFPP_CONTROLLER, OFPCML_NO_BUFFER)]`).
  - Switches must never default to standalone / normal MAC-learning mode (`fail_mode=secure` on OVS).
- **Flow Priority Hierarchy:**
  - `Priority 100` — **Health Probing & Control Bypass** (Direct ICMP/TCP to physical IPs for monitoring).
  - `Priority 50` — **Forward VIP NAT Rewrite** (Client -> VIP:Port rewritten to Backend Real IP:Port and MAC).
  - `Priority 40` — **Reverse VIP NAT Rewrite** (Backend Real IP:Port rewritten back to VIP:Port and VIP MAC).
  - `Priority 30` — **ARP Handling & VIP Resolution** (ARP requests for VIP answered with VIP Virtual MAC).
  - `Priority 20` — **Traffic Engineering Overrides** (Alternate path routing upon link utilization threshold breach).
  - `Priority 10` — **Standard Unicast Forwarding** (Host-to-host learned L2/L3 forwarding).
  - `Priority 0` — **Default Table-Miss** (Send packet to controller via Packet-In).

---

## 2. Controller Architecture & Coding Rules
- **Modular App Design:** Maintain clean separation of concerns under `controller/`:
  - `controller/main.py`: RyuApp orchestrator and event distributor.
  - `controller/config.py`: Centralized configuration (VIP, backend pool IPs/MACs/ports, thresholds).
  - `controller/flow_manager.py`: Reusable OFP 1.3 flow mod, match, and action builder functions.
  - `controller/load_balancer.py`: Selection algorithms (Round-Robin, Least-Connections, Weighted).
  - `controller/topology_discovery.py`: Switch, link, and port discovery.
  - `controller/stats_monitor.py`: Periodic port and flow stats polling with bandwidth computation.
  - `controller/health_checker.py`: Active health probing and backend pool state management.
  - `controller/traffic_engineer.py`: Dynamic alternate path calculation and flow rerouting.
- **Ryu Greenthread Safety:**
  - Any periodic polling or background loop must use Ryu's `hub.spawn()` and `hub.sleep()`. Never use standard blocking `time.sleep()`.
  - Handle exceptions inside event callbacks gracefully to avoid killing greenthreads.
- **Flow Timeout Conventions:**
  - Active client-to-backend TCP session flows must use `idle_timeout=20` and `hard_timeout=60` to ensure prompt flow reclamation after connection termination.
  - Permanent infrastructure rules (Table-Miss, ARP responder, default bypass) must have `idle_timeout=0` and `hard_timeout=0`.

---

## 3. Mininet & Data Plane Conventions
- **Topology Layout (`topology/lb_topology.py`):**
  - Minimum of 2 switches with redundant links forming at least two disjoint/divergent paths.
  - Clients: `h1`, `h2` (`10.0.0.1`, `10.0.0.2`).
  - Backend Servers: `s1_srv` (`10.0.0.11`), `s2_srv` (`10.0.0.12`), `s3_srv` (`10.0.0.13`), `s4_srv` (`10.0.0.14`).
  - Virtual IP (VIP): `10.0.0.100` with virtual MAC `00:00:00:00:00:fe`.
  - Links: Use `TCLink` with explicit bandwidth (`bw=10` Mbps) and delay (`delay='2ms'`) for observable traffic engineering behavior.
- **Environment Cleanliness:**
  - Always run `sudo mn -c` before initiating Mininet sessions.

---

## 4. Verification & Testing Standards (TDAI)
- Every algorithm and mechanism must have reproducible verification:
  1. `tests/test_vip_rewrite.py`: Verify bidirectional NAT flow table entries and end-to-end curl responses.
  2. `tests/test_lb_algorithms.py`: Verify distribution ratios across Round-Robin, Least-Connections, and Weighted.
  3. `tests/test_failover.py`: Measure recovery time upon backend crash and switch link teardown.
- Benchmark results must produce verifiable JSON/CSV logs and Matplotlib visual figures.
