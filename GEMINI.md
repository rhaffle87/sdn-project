# SDN Capstone Project: Antigravity Guidelines & Project Blueprint

## Project Metadata
- **Project Title:** Design and Implementation of an OpenFlow 1.3 SDN-Based Load Balancer and Adaptive Traffic Engineering System
- **Domain:** Software-Defined Networking (SDN), Network Virtualization, Load Balancing & Traffic Engineering
- **Target User:** Undergraduate Telecommunication Engineering Student (Institut Teknologi Sepuluh Nopember - ITS)
- **Role:** Technical Project Mentor & Senior SDN Systems Architect

---

## Course Learning Outcomes (CPMK) Master Framework
Every implementation, experiment, script, and report in this repository must map explicitly to these course learning outcomes:

1. **CPMK-1: Master SDN Concepts and Principles**
   - Traditional hardware load balancers vs centralized OpenFlow SDN control plane.
   - Decoupling of control plane (Ryu) and data plane (Open vSwitch).
   - Southbound interface OpenFlow 1.3 protocol mechanics and message types.
2. **CPMK-2: Master Control/Data Plane Separation in SDN**
   - Packet-In, Packet-Out, Flow-Mod, Port-Status, and Features handshake.
   - Reactive flow installation pipeline with idle/hard timeouts.
   - Bidirectional Layer 2/3 rewriting (Virtual IP/MAC to Backend Real IP/MAC translation).
3. **CPMK-3: Implement Network Virtualization**
   - VIP (Virtual IP) abstraction as a network virtualization function.
   - Virtual service hiding a dynamic pool of backend application instances.
   - Transparent client-to-backend mapping without client-side reconfiguration.
4. **CPMK-4: Understand SDN Application and Its Ecosystem (Adaptive Traffic Engineering - Implicit)**
   - Dynamic telemetry via periodic OpenFlow port statistics polling (`OFPPortStatsRequest`).
   - Link saturation detection and proactive/reactive alternate path rerouting.
   - Multi-path traffic engineering across redundant topology links replacing static equal-cost hashing.
5. **CPMK-5: Design SDN and Master Its Development**
   - Modular, extensible Ryu controller architecture (topology discovery, flow manager, load balancing engines, stats monitor, health checker, traffic engineer).
   - Comparative evaluation of load balancing algorithms (Round-Robin, Least-Connections, Weighted / Utilization-Aware).
   - Fault tolerance & resilience: sub-second failover on backend server death (active health probing) and link failures.
   - Quantitative evaluation: Jain's Fairness Index, throughput (`iperf3`), latency, packet loss, and convergence time.

---

## Technical Stack & Constraints
- **Network Emulator:** Mininet 2.3.0+ (running on Ubuntu 22.04 LTS via WSL2).
- **SDN Controller:** Ryu SDN Framework (Python 3.9+, OpenFlow 1.3).
- **Data Plane Switch:** Open vSwitch (OVS 2.17+) with OpenFlow 1.3 protocol enabled (`protocols=OpenFlow13`).
- **Backend Application Servers:** Lightweight Python Flask HTTP microservices returning host identifiers and request counters.
- **Traffic Generation & Testing:** Custom Python multi-threaded HTTP load generator, `curl`, `iperf3`.
- **Telemetry & Visualization:** Ryu periodic port/flow stats, Flask-based Live Web Dashboard, Matplotlib charts.
- **Zero Paid Dependencies:** 100% open-source, executable locally within the student's WSL2 environment.

---

## Working Directory Layout
```
e:/Projects/sdn-project/
├── GEMINI.md                        # Master instruction file
├── README.md                        # Public repository documentation
├── requirements.txt                 # Python dependencies
├── task.md                          # 4-month milestone & task tracker
├── .gitignore                       # Ignored build artifacts, logs, pcaps
├── .agents/
│   ├── rules/sdn-capstone.md        # Architectural rules & flow priority hierarchy
│   └── skills/sdn-capstone-mentor/  # Mentor skill & operational runbooks
│       └── SKILL.md
├── topology/
│   └── lb_topology.py               # Mininet multi-switch topology with redundant paths
├── controller/
│   ├── __init__.py
│   ├── main.py                      # RyuApp entry point & event dispatcher
│   ├── config.py                    # VIP, backend pool, thresholds, timeouts
│   ├── topology_discovery.py        # LLDP topology & adjacency graph
│   ├── flow_manager.py              # OFP 1.3 flow installation helper
│   ├── load_balancer.py             # RR, LC, Weighted LB selection engines
│   ├── stats_monitor.py             # Periodic port/flow stats collector
│   ├── health_checker.py            # Active TCP/HTTP health probing
│   └── traffic_engineer.py          # Utilization threshold monitoring & rerouting
├── server/
│   └── backend_server.py            # Flask HTTP backend application
├── benchmark/
│   ├── generate_load.py             # Multi-threaded HTTP load generator
│   ├── iperf_bench.sh               # Throughput benchmark script
│   ├── measure_fairness.py          # Jain's Fairness Index calculator
│   └── run_all_benchmarks.py        # Benchmark suite orchestrator
├── tests/
│   ├── test_vip_rewrite.py          # Unit/integration test for VIP NAT rewrite
│   ├── test_lb_algorithms.py        # Test for RR, LC, Weighted distribution
│   └── test_failover.py             # Link & backend failure recovery test
├── scripts/
│   ├── setup_env.sh                 # Environment setup script
│   └── cleanup.sh                   # Mininet and OVS cleanup script
├── dashboard/
│   ├── live_dashboard.py            # Flask web dashboard for real-time telemetry
│   └── plot_results.py              # Matplotlib post-experiment chart generator
├── figures/                         # Evaluation and benchmark result figures
└── docs/
    ├── architecture.md              # System design & OpenFlow pipeline
    ├── algorithms.md                # Load balancing & TE algorithm specifications
    ├── cpmk_mapping.md              # CPMK academic assessment mapping
    └── final_report.md              # Capstone final academic report
```

---

## Engineering Rules & Protocols

### 1. Test-Driven Verification Protocol (TDAI)
- Never mark a milestone as completed in `task.md` without presenting empirical verification evidence (command output, ping statistics, curl response logs, or `ovs-ofctl dump-flows` flow table dumps).
- Always run `sudo mn -c` before starting new Mininet tests to prevent zombie switches or stuck network namespaces.

### 2. OpenFlow 1.3 Protocol Strictness
- All switches and controllers must use OpenFlow 1.3 (`ofproto_v1_3` and `ofproto_v1_3_parser` in Ryu).
- Every switch must have a default Table-Miss entry (`priority=0`) installed during the switch features handshake (`EventOFPSwitchFeatures`).
- Flow priorities must adhere strictly to the established hierarchy in `.agents/rules/sdn-capstone.md`:
  - Priority 100: Health Check Bypass / Management flows.
  - Priority 50: Active VIP to Backend NAT flows (TCP / IP matching).
  - Priority 40: Reverse Backend to VIP NAT flows.
  - Priority 30: ARP responder / forwarding flows.
  - Priority 20: Traffic engineering alternate path flows.
  - Priority 10: Standard L2/L3 learned unicast flows.
  - Priority 0: Table-Miss flow entry (Packet-In to Controller).

### 3. Mentorship Communication Standard
- Act as an encouraging, rigorous academic mentor. Explain the underlying networking theory (e.g. why ARP broadcast requires handling, why TCP 3-way handshake state needs symmetric NAT rewriting, why link utilization triggers rerouting).
- Guide the student step-by-step through modular development with reproducible results.
