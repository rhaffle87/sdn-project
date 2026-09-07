# SDN-Based Load Balancer and Adaptive Traffic Engineering System

[![OpenFlow 1.3](https://img.shields.io/badge/OpenFlow-1.3-blue.svg)](https://opennetworking.org/sdn-resources/openflow/)
[![Ryu Framework](https://img.shields.io/badge/Controller-Ryu%204.34-green.svg)](https://ryu-sdn.org/)
[![Mininet](https://img.shields.io/badge/Emulator-Mininet%202.3.0-orange.svg)](http://mininet.org/)
[![Open vSwitch](https://img.shields.io/badge/vSwitch-OVS%202.17%2B-purple.svg)](https://www.openvswitch.org/)

An OpenFlow 1.3 Software-Defined Networking (SDN) load balancer and adaptive traffic engineering system built using the **Ryu SDN framework** and emulated in **Mininet** with **Open vSwitch (OVS)**. 

This project demonstrates how programmable control planes can replace expensive proprietary hardware load balancers by dynamically distributing client traffic across a virtual pool of backend application servers with bidirectional Layer 2/Layer 3 address rewriting (NAT), dynamic telemetry-driven path optimization, and active health monitoring.

---

## 🎓 Academic Alignment: Course Learning Outcomes (CPMK)

| CPMK | Outcome | Project Implementation |
|---|---|---|
| **CPMK-1** | Master SDN Concepts and Principles | Decoupling of control and data planes; Southbound OpenFlow 1.3 handshake; Reactive flow programming. |
| **CPMK-2** | Master Control/Data Plane Separation in SDN | Packet-In, Flow-Mod, Port-Status handlers; Flow table pipeline (Table-Miss, priorities, timeouts); Symmetrical bidirectional NAT rewrite. |
| **CPMK-3** | Implement Network Virtualization | Virtual IP (VIP) and Virtual MAC abstraction; Virtual service exposing a dynamic backend server pool without client reconfiguration. |
| **CPMK-4** | Understand SDN Application and Its Ecosystem | Adaptive Traffic Engineering; Real-time link bandwidth utilization monitoring via `OFPPortStatsRequest`; Alternate path rerouting upon threshold saturation. |
| **CPMK-5** | Design SDN and Master Its Development | Modular Ryu architecture; Multi-algorithm comparison (Round-Robin, Least-Connections, Weighted); Sub-second health-check failover; Jain's Fairness Index & throughput evaluation. |

---

## 🏛️ System Architecture

```
                      +---------------------------------------+
                      |            Ryu Controller             |
                      |  +---------------------------------+  |
                      |  |   Load Balancing Engine         |  |
                      |  |   (Round-Robin / LC / Weighted) |  |
                      |  +---------------------------------+  |
                      |  | Telemetry & Traffic Engineering |  |
                      |  | Health Checker & REST Exporter  |  |
                      |  +---------------------------------+  |
                      +-------------------+-------------------+
                                          |
                      Southbound OpenFlow 1.3 (TCP 6653)
                                          |
            +-----------------------------+-----------------------------+
            |                                                           |
     +------v------+              Path A (Primary)               +------v------+
     |  Switch s1  |=============================================|  Switch s2  |
     +------+------+                                             +------+------+
            |                     Path B (Alternate)                    |
            |===========================================================|
            |                                                           |
   +--------+--------+                                         +--------+--------+
   |                 |                                         |   |        |    |
[Client h1]     [Client h2]                                  [srv1] [srv2] [srv3] [srv4]
(10.0.0.1)      (10.0.0.2)                                    (10.0.0.11 .. 10.0.0.14)
   
   VIP: 10.0.0.100 (Virtual MAC: 00:00:00:00:00:fe)
```

### Flow Priority Hierarchy
1. **Priority 100:** Health Probing / Control Plane Bypass
2. **Priority 50:** Client to Backend Forward NAT Rewrite (VIP $\rightarrow$ Backend Real IP/MAC)
3. **Priority 40:** Backend to Client Reverse NAT Rewrite (Backend Real IP/MAC $\rightarrow$ VIP)
4. **Priority 30:** Virtual IP ARP Responder
5. **Priority 20:** Traffic Engineering Overrides (Alternate Path Routing)
6. **Priority 10:** Standard Learned Unicast Forwarding
7. **Priority 0:** Default Table-Miss (Send to Controller)

---

## 📁 Repository Structure

```
.
├── GEMINI.md                        # Master project guidelines & blueprint
├── task.md                          # Milestone and task progress tracker
├── README.md                        # Project documentation (this file)
├── requirements.txt                 # Python dependencies
├── .gitignore                       # Git ignore file
├── .agents/                         # IDE rules and capstone mentor skill
├── topology/
│   └── lb_topology.py               # Mininet multi-switch topology with redundant links
├── controller/
│   ├── main.py                      # RyuApp entry point & event distribution
│   ├── config.py                    # VIP, backend pool, and timeout parameters
│   ├── topology_discovery.py        # Switch and link discovery
│   ├── flow_manager.py              # OFP 1.3 Flow-Mod helper utilities
│   ├── load_balancer.py             # RR, LC, and Weighted LB algorithms
│   ├── stats_monitor.py             # Periodic port and flow stats polling
│   ├── health_checker.py            # Active TCP/HTTP backend probing
│   └── traffic_engineer.py          # Bandwidth utilization rerouting engine
├── server/
│   └── backend_server.py            # Flask HTTP backend microservice
├── benchmark/
│   ├── generate_load.py             # Concurrent HTTP request load generator
│   ├── iperf_bench.sh               # Throughput testing script
│   ├── measure_fairness.py          # Jain's Fairness Index calculator
│   └── run_all_benchmarks.py        # Automated benchmark orchestrator
├── tests/
│   ├── test_vip_rewrite.py          # VIP NAT verification test
│   ├── test_lb_algorithms.py        # Algorithm load distribution test
│   └── test_failover.py             # Backend & link failover benchmark
├── scripts/
│   ├── setup_env.sh                 # Environment setup script
│   └── cleanup.sh                   # Mininet and OVS cleanup script
├── dashboard/
│   ├── live_dashboard.py            # Web telemetry dashboard
│   └── plot_results.py              # Post-experiment charting script
├── figures/                         # Generated evaluation figures
└── docs/
    ├── architecture.md              # Detailed architecture & flow table design
    ├── algorithms.md                # Algorithm comparative analysis
    ├── cpmk_mapping.md              # Academic assessment evidence
    └── final_report.md              # Capstone final report
```

---

## 🚀 Getting Started

### 1. Prerequisites (WSL2 / Ubuntu 22.04 LTS)
Ensure Open vSwitch and Mininet are installed:
```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip iperf3
```

### 2. Python Virtual Environment
Use the dedicated SDN virtual environment:
```bash
source /home/rafli_alif/sdn-venv/bin/activate
pip install -r requirements.txt
```

### 3. Launching the Controller
Start the modular Ryu controller with OpenFlow 1.3 listening on port 6653:
```bash
/home/rafli_alif/sdn-venv/bin/ryu-manager controller/main.py --ofp-tcp-listen-port 6653
```

### 4. Launching Mininet Topology
In a second terminal, clean up any previous sessions and launch the topology:
```bash
sudo mn -c
sudo /home/rafli_alif/sdn-venv/bin/python3 topology/lb_topology.py
```

### 5. Running Verification Tests
```bash
# Automated single-command test runner (cleans OVS, starts Ryu, awaits port 6653, and executes test):
./scripts/run_test.sh tests/test_vip_rewrite.py
./scripts/run_test.sh tests/test_lb_algorithms.py
./scripts/run_test.sh tests/test_failover.py
```

### 6. Launching Live Web Dashboard
```bash
# In a third terminal (with Ryu controller running):
/home/rafli_alif/sdn-venv/bin/python3 dashboard/live_dashboard.py
# Access dashboard at: http://localhost:8081
```

### 7. Running Full Benchmark Suite & Chart Generation
```bash
# Execute automated multi-algorithm benchmarks (24 requests x 3 algorithms)
sudo /home/rafli_alif/sdn-venv/bin/python3 benchmark/run_all_benchmarks.py

# Re-generate scientific figures in figures/ directory
/home/rafli_alif/sdn-venv/bin/python3 dashboard/plot_results.py
```

