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

```mermaid
flowchart TD
    subgraph Controller ["Ryu Controller"]
        subgraph LBEngine ["Load Balancing Engine"]
            RR["Round-Robin"]
            LC["Least-Connections"]
            WRR["Weighted"]
        end
        subgraph TEEngine ["Telemetry & Traffic Engineering"]
            Stats["Stats Monitor (Port Stats Polling)"]
            TE["Traffic Engineer (Rerouting Engine)"]
        end
        subgraph HealthEngine ["Health Checker & REST Exporter"]
            HC["Active Health Prober (/health)"]
            REST["REST API (:8080/api)"]
        end
    end
    Controller <-->|"Southbound OpenFlow 1.3 (TCP 6653)"| S1
    Controller <-->|"Southbound OpenFlow 1.3 (TCP 6653)"| S2
    subgraph DataPlane ["Data Plane (Open vSwitch)"]
        S1["Switch s1 (Ingress)"]
        S2["Switch s2 (Egress)"]
        S1 ===|"Path A (Primary Link)"| S2
        S1 -.-|"Path B (Alternate Link)"| S2
    end
    subgraph Clients ["Client Hosts"]
        H1["Client h1<br/>10.0.0.1"]
        H2["Client h2<br/>10.0.0.2"]
    end
    subgraph VIPBox ["Virtual Service Abstraction"]
        VIP["Virtual IP: 10.0.0.100<br/>Virtual MAC: 00:00:00:00:00:fe"]
    end
    subgraph Servers ["Backend Server Farm"]
        SRV1["srv1 (10.0.0.11)"]
        SRV2["srv2 (10.0.0.12)"]
        SRV3["srv3 (10.0.0.13)"]
        SRV4["srv4 (10.0.0.14)"]
    end
    H1 --- S1
    H2 --- S1
    VIPBox -.-> S1
    S2 --- SRV1
    S2 --- SRV2
    S2 --- SRV3
    S2 --- SRV4
```

### 1.2 Physical Realization: 4-Switch Diamond Mesh Topology

In practical Open vSwitch networks, connecting parallel unbonded links directly between two switches introduces Layer 2 loops and MAC address flapping. To enable deterministic multi-path traffic engineering, the underlying data plane is realized as a **4-switch Diamond Mesh** ([`topology/lb_topology.py`](topology/lb_topology.py)):

```mermaid
flowchart LR
    subgraph Clients ["Client Layer"]
        H1["Client h1<br/>10.0.0.1"]
        H2["Client h2<br/>10.0.0.2"]
    end
    subgraph IngressLayer ["Ingress Layer"]
        S1["Switch s1 (Ingress LB)<br/>dpid: 1"]
    end
    subgraph CoreLayer ["Traffic Engineering Transit Core"]
        S2["Switch s2 (Transit)<br/><b>Path A (Primary)</b><br/>10 Mbps, 2ms"]
        S3["Switch s3 (Transit)<br/><b>Path B (Alternate)</b><br/>10 Mbps, 2ms"]
    end
    subgraph EgressLayer ["Egress Layer"]
        S4["Switch s4 (Server Gateway)<br/>dpid: 4"]
    end
    subgraph Backends ["Backend Farm (Flask Microservices)"]
        SRV1["srv1 (10.0.0.11)<br/>Weight: 1"]
        SRV2["srv2 (10.0.0.12)<br/>Weight: 2"]
        SRV3["srv3 (10.0.0.13)<br/>Weight: 1"]
        SRV4["srv4 (10.0.0.14)<br/>Weight: 2"]
    end
    H1 -->|Port 1| S1
    H2 -->|Port 2| S1
    S1 -->|Port 3| S2
    S1 -->|Port 4| S3
    S2 -->|Port 2| S4
    S3 -->|Port 2| S4
    S4 -->|Port 1| SRV1
    S4 -->|Port 2| SRV2
    S4 -->|Port 3| SRV3
    S4 -->|Port 4| SRV4
```

---

### OpenFlow 1.3 Flow Priority Hierarchy

| Priority | Match Conditions | OpenFlow Actions | Timeouts | Subsystem |
|---|---|---|---|---|
| **100** | `eth_type=0x0800, ip_proto=6, ipv4_src=10.0.0.254, ipv4_dst={10.0.0.11-14}` | `OUTPUT:backend_port` (Bypass NAT) | `idle=0, hard=0` | Health Checker |
| **50** | `eth_type=0x0800, ip_proto=6, ipv4_src=client_ip, ipv4_dst=10.0.0.100, tcp_dst=80` | `SET_FIELD(ipv4_dst=srv_ip)`, `SET_FIELD(eth_dst=srv_mac)`, `OUTPUT:transit_port` | `idle=20s, hard=60s` | Forward NAT |
| **40** | `eth_type=0x0800, ip_proto=6, ipv4_src=srv_ip, ipv4_dst=client_ip, tcp_src=80` | `SET_FIELD(ipv4_src=10.0.0.100)`, `SET_FIELD(eth_src=00:00:00:00:00:fe)`, `OUTPUT:client_port` | `idle=20s, hard=60s` | Reverse NAT |
| **30** | `eth_type=0x0806, arp_tpa=10.0.0.100` | Controller Proxy ARP Reply (`00:00:00:00:00:fe`) | `idle=0, hard=0` | Proxy ARP |
| **20** | `eth_type=0x0800, ip_proto=6, ipv4_dst=backend_ip` | `OUTPUT:alternate_transit_port` (Path B Override) | `idle=30s, hard=120s` | Traffic Engineering |
| **10** | `eth_dst=host_mac` | `OUTPUT:learned_port` | `idle=30s, hard=60s` | Learned L2 Forwarding |
| **0** | `match=*` (Wildcard Table-Miss) | `OUTPUT:OFPP_CONTROLLER` (`OFPCML_NO_BUFFER`) | Permanent | Reactive Setup |

---

## 🔬 Step-by-Step Implementation Mechanics & Pipeline Architecture

### Step 1: OpenFlow 1.3 Control Plane Handshake & Table-Miss Installation
- **Code:** [`controller/main.py`](controller/main.py#L64-L112) (`switch_features_handler`) | **CPMK:** CPMK-1, CPMK-2
- **Mechanism:** During switch connection, Ryu intercepts `EventOFPSwitchFeatures` and immediately installs a default Table-Miss entry (`priority=0`) on Table 0 with `OFPMatch()` and `OFPActionOutput(OFPP_CONTROLLER, OFPCML_NO_BUFFER)`.
- **Reasoning & Rationale:** Open vSwitch runs in `fail_mode=secure`. Unlike legacy OpenFlow 1.0 switches, OpenFlow 1.3 switches silently drop unmatched packets unless an explicit Priority 0 Table-Miss rule exists.
- **Edge Case Prevention:**
  - *Initial TCP SYN Drop:* If `OFPCML_NO_BUFFER` (65535) is omitted, switches buffer packet payloads internally. If the switch buffer overruns or expires, the initial SYN is lost, triggering a severe 3-second TCP SYN retransmission timeout. Setting `OFPCML_NO_BUFFER` forces complete payload encapsulation inside the `OFPT_PACKET_IN` message.

---

### Step 2: Virtual IP Abstraction & Proxy ARP Engine
- **Code:** [`controller/load_balancer.py`](controller/load_balancer.py#L113-L144) (`handle_arp`) | **CPMK:** CPMK-3
- **Mechanism:** When client `h1` or `h2` issues an ARP broadcast (`"Who has 10.0.0.100?"`), switch `s1` forwards the packet to Ryu. The controller intercepts the request, constructs an ARP reply with Virtual MAC `00:00:00:00:00:fe`, and sends it directly back out the ingress port via `send_packet_out`.
- **Reasoning & Rationale:** Enables seamless network virtualization. Clients interact with a single virtual endpoint without knowing the backend server IP or MAC addresses.
- **Edge Case Prevention:**
  - *Broadcast Storms:* Flooding ARP requests into redundant mesh loops causes infinite packet replication. The controller acts as a strict Proxy ARP responder, never flooding ARP requests across transit links.
  - *Client ARP Cache Staling:* If clients cached real server MACs, server failovers would abruptly sever TCP sockets. The static Virtual MAC guarantees seamless re-routing.

---

### Step 3: Layer 4 Session Interception & Multi-Algorithm Load Balancing
- **Code:** [`controller/load_balancer.py`](controller/load_balancer.py#L52-L86) (`select_backend`) | **CPMK:** CPMK-5
- **Mechanism:** The first TCP SYN targeting `10.0.0.100:80` triggers backend scheduling using one of three pluggable algorithms:
  1. **Round-Robin (RR):** Rotates sequentially across active healthy backends via modulo counter.
  2. **Least-Connections (LC):** Dynamically assigns traffic to the server with the lowest count of live flows.
  3. **Weighted (WRR):** Dispatches requests proportional to configured capacity weights (e.g. `1:2:1:2`).
- **Reasoning & Rationale:** Provides architectural flexibility to handle heterogeneous server hardware and variable request execution durations.
- **Edge Case Prevention:**
  - *Connection Count Drift in LC:* If clients crash without sending TCP FIN/RST packets, connection counters could drift. The system sets `OFPFF_SEND_FLOW_REM` on flow rules; when inactive rules expire in OVS, Ryu's `EventOFPFlowRemoved` handler automatically decrements the server's active connection count.

---

### Step 4: Symmetrical Bidirectional Layer 2/3 NAT Address Rewriting
- **Code:** [`controller/load_balancer.py`](controller/load_balancer.py#L145-L270) (`install_nat_flows`) | **CPMK:** CPMK-2, CPMK-3
- **Mechanism:** Ryu installs symmetric flow rules across the ingress, transit, and egress switches:
  - **Forward Rule (s1, Priority 50):** Rewrites `ipv4_dst` from VIP `10.0.0.100` to the real backend IP (`10.0.0.11-14`) and `eth_dst` to backend MAC.
  - **Reverse Rule (s1, Priority 40):** Rewrites `ipv4_src` from backend IP back to `10.0.0.100` and `eth_src` back to `00:00:00:00:00:fe`.
- **Reasoning & Rationale:** TCP sockets are bound to the client-selected 4-tuple (`src_ip`, `src_port`, `dst_ip`, `dst_port`). If a backend replies with its real IP, the client kernel immediately drops the packet and responds with a TCP RST.
- **Edge Case Prevention:**
  - *SYN Forwarding Race:* To prevent dropping the initial SYN packet while `FlowMod` messages are propagating to OVS, Ryu simultaneously injects the rewritten SYN packet along the chosen transit path via `send_packet_out`.

---

### Step 5: Active Layer 7 Application Health Probing & Dynamic Failover
- **Code:** [`controller/health_checker.py`](controller/health_checker.py) | **CPMK:** CPMK-5
- **Mechanism:** A background greenlet thread probes `http://<backend_ip>:80/health` every 10 seconds (`timeout=3.0s`, `HEALTH_CHECK_INTERVAL=10`).
  - If a backend fails 5 consecutive checks (`HEALTH_FAIL_LIMIT=5`), it is marked `DOWN`, removed from the load-balancing candidate pool, and existing flow rules are proactively flushed using `OFPFC_DELETE` (failover tests also support instantaneous administrative failover via `/api/backend/health`).
  - When the backend recovers (1 successful probe), it is automatically restored to the scheduling pool.
- **Reasoning & Rationale:** Layer 2 link carrier detection does not detect application deadlocks or HTTP 500 errors. Active Layer 7 probing ensures traffic is never dispatched to broken microservices.
- **Edge Case Prevention:**
  - *Probe Rewriting Interference:* Controller health probes originating from host management IP `10.0.0.254` are matched by dedicated `Priority 100` rules on switch `s4` that output directly to the backend ports without undergoing VIP translation.

---

### Step 6: Real-Time Telemetry & Adaptive Traffic Engineering
- **Code:** [`controller/stats_monitor.py`](controller/stats_monitor.py), [`controller/traffic_engineer.py`](controller/traffic_engineer.py) | **CPMK:** CPMK-4
- **Mechanism:** Ryu polls port statistics every 5 seconds via `OFPPortStatsRequest`. Throughput and link utilization are calculated using delta byte counters:

  $$\text{Throughput (bps)} = \frac{(B_t - B_{t-\Delta t}) \times 8}{\Delta t}$$

  $$\text{Utilization} = \frac{\text{Throughput}}{10\text{ Mbps}} \times 100$$

  - When Path A (Primary Transit) exceeds 80% link utilization, new TCP sessions are automatically routed across Path B (Alternate Transit via `s3`).
- **Reasoning & Rationale:** Replaces static equal-cost multi-path hashing (which suffers from hash collisions and elephant flow congestion) with dynamic telemetry-driven path steering.
- **Edge Case Prevention:**
  - *Route Flapping & Oscillation:* To prevent rapid back-and-forth oscillation between paths, the traffic engineer implements **hysteresis damping**: traffic shifts to Path B at 80% utilization, but will not revert to Path A until Path A utilization drops below 50% for two consecutive polling cycles.

---

### Step 7: Benchmarking, Jain's Fairness & Live Observability
- **Code:** [`benchmark/measure_fairness.py`](benchmark/measure_fairness.py), [`dashboard/live_dashboard.py`](dashboard/live_dashboard.py) | **CPMK:** CPMK-5
- **Mechanism:**
  - Computes standard and Weighted Jain's Fairness Index ($J$):
    $$J(x_1, x_2, \dots, x_n) = \frac{\left(\sum_{i=1}^n x_i\right)^2}{n \cdot \sum_{i=1}^n x_i^2}$$
  - Flask web dashboard (`:8081`) visualizes real-time per-backend request counts, active connections, link bandwidth utilization, and health status:

![Figure: Live Web Telemetry Dashboard](figures/dashboard_full_system_verified.png)

- **Benchmark Highlights (72 requests, concurrency C = 4):**
  - **Round-Robin:** Achieved perfect mathematical fairness (JFI = 1.0000) with uniform 18:18:18:18 distribution, 100% request completion, and top throughput (32.13 RPS).
  - **Least-Connections:** Achieved perfect mathematical fairness (JFI = 1.0000) with uniform 18:18:18:18 request distribution and the lowest average latency (33.87 ms).
  - **Weighted (1:2:1:2):** Achieved ideal normalized fairness (Weighted JFI = 1.0000) with exact 12:24:12:24 load distribution matching configured capacities.

---

> 📘 **Comprehensive Academic Documentation Suite:**
> - [**Load Balancing & Traffic Engineering Algorithms**](docs/algorithms.md): Detailed mathematical models, complexity, and scientific charts.
> - [**System Architecture Specification**](docs/architecture.md): Decoupling principles, flow pipeline, sequence diagrams, and annotated OVS dumps.
> - [**Architecture Deep-Dive & Critical Review**](docs/system_architecture.md): Implementation mechanics, edge cases, and risk mitigation matrix.
> - [**CPMK Academic Evidence Mapping**](docs/cpmk_mapping.md): Rubric mapping for ITS Department of Telecommunication Engineering.
> - [**Final Capstone Report**](docs/final_report.md): Formal research paper covering abstract, theory, methodology, empirical results, and references.

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
│   ├── setup_env.sh                 # Environment setup script (with clean.py patch)
│   ├── cleanup.sh                   # Mininet and OVS cleanup script
│   └── run_test.sh                  # Automated single-command test orchestrator
├── dashboard/
│   ├── live_dashboard.py            # Web telemetry dashboard
│   └── plot_results.py              # Post-experiment charting script
├── figures/                         # Generated evaluation figures
└── docs/
    ├── architecture.md              # Detailed architecture & flow table design
    ├── system_architecture.md       # Exhaustive pipeline mechanics, edge cases & review
    ├── algorithms.md                # Algorithm comparative analysis
    ├── cpmk_mapping.md              # Academic assessment evidence
    └── final_report.md              # Capstone final report
```

---

## 🚀 End-to-End Operational Guide (WSL2 & Windows PowerShell)

This guide provides a comprehensive, step-by-step operational workflow for running, testing, and benchmarking the SDN Load Balancer and Traffic Engineering platform. Every step includes dual-track command examples:
- 🐧 **Native WSL2 Terminal (Ubuntu 22.04 LTS Bash)**: For running directly inside an interactive WSL2 shell.
- 🪟 **Windows PowerShell (`wsl` CLI)**: For executing commands directly from Windows PowerShell without switching into an interactive Linux session.

> 💡 **Directory Navigation Rule (No Hardcoded Paths):**
> Open your terminal (PowerShell or WSL2 Bash) and navigate to the root directory where you cloned this repository:
> - **In Windows PowerShell:** `cd <path\to\cloned\sdn-project>` (e.g. `cd C:\Users\Username\sdn-project` or `cd D:\sdn-project`)
> - **In WSL2 Linux Shell:** `cd <path/to/cloned/sdn-project>` (e.g. `cd ~/sdn-project` or `cd /mnt/c/Users/.../sdn-project`)
> 
> *Notice for Windows PowerShell users:* When you execute `wsl` commands from inside your cloned repository directory in PowerShell, WSL automatically inherits your current working directory. You do **not** need to hardcode absolute Linux mount paths!

---

### 🖥️ Architecture & Terminal Coordination

In a Software-Defined Network, the centralized control plane is physically separated from data plane forwarding. To observe real-time packet processing, telemetry, and live failover, standard operation coordinates four logical terminal roles:

| Terminal / Role | Component | Network Endpoints | Primary Function |
| :--- | :--- | :--- | :--- |
| **Terminal 1** | **Ryu SDN Controller** | `0.0.0.0:6653` (OpenFlow 1.3)<br>`0.0.0.0:8080` (WSGI REST API) | Runs event loops, installs flow tables, tracks active TCP connections, and calculates port telemetry. |
| **Terminal 2** | **Mininet Data Plane** | OVS Switches `s1`–`s4`<br>Hosts `h1`–`h2`, `s1_srv`–`s4_srv` | Emulates diamond topology, runs 4 background Flask HTTP servers (`:80`), and exposes the interactive `mininet>` CLI. |
| **Terminal 3** | **Live Telemetry Dashboard** | `http://localhost:8081` (Flask Web UI) | Enterprise operations console displaying live topology, bandwidth gauges, JFI fairness meter, and server health. |
| **Terminal 4** | **Experimenter Console** | CLI Probes / REST Client | Injects HTTP traffic, triggers runtime algorithm changes, injects link congestion, and executes benchmark scripts. |

> 💡 **Network Port Mapping Reference:**
> - **OpenFlow Southbound Channel:** `tcp:6653`
> - **Ryu Controller REST API:** `http://localhost:8080`
> - **Live Telemetry Web Dashboard:** `http://localhost:8081`
> - **WSL2 Automatic Port Forwarding:** WSL2 automatically forwards ports `6653`, `8080`, and `8081` to the Windows host, allowing direct browser access to `http://localhost:8081`.

---

### 📋 Step 1: System Prerequisites & Environment Setup

Ensure your WSL2 environment has the required Open vSwitch kernel modules, Mininet packages, and Python build dependencies.

#### 1.1 Check WSL2 Version
Open **Windows PowerShell** and confirm your Ubuntu distribution is running WSL Version 2:
```powershell
wsl -l -v
```

🔍 **Crosscheck & Verification:**
- Look for `VERSION: 2` next to your default distribution (e.g. `Ubuntu-22.04`).
- *(If your distribution indicates Version 1, upgrade with: `wsl --set-version <distro-name> 2`)*

---

#### 1.2 Install Required System Packages
Install Mininet, Open vSwitch, Python pip, virtual environment tools, and iperf3:

**🐧 Native WSL2 Terminal (Bash):**
```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip python3-venv iperf3
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -u root apt update
wsl -u root apt install -y mininet openvswitch-switch python3-pip python3-venv iperf3
```

🔍 **Crosscheck & Verification CLI:**
Run version checks to confirm all core system tools are installed:

- **🐧 WSL Bash:**
  ```bash
  mn --version && ovs-vsctl --version | head -n 1 && iperf3 --version | head -n 1 && python3 --version
  ```
- **🪟 PowerShell:**
  ```powershell
  wsl mn --version; wsl ovs-vsctl --version | Select-Object -First 1; wsl iperf3 --version | Select-Object -First 1; wsl python3 --version
  ```
- **Expected Output:**
  ```
  2.3.0 (Mininet)
  ovs-vsctl (Open vSwitch) 2.17+
  iperf 3.9+
  Python 3.9+
  ```

---

#### 1.3 Run Environment Setup & Mininet Patch
Execute [`./scripts/setup_env.sh`](scripts/setup_env.sh). This automated script:
1. Verifies that `mn`, `ovs-vsctl`, and `iperf3` are available.
2. Ensures the `openvswitch-switch` daemon is active.
3. **Patches `/usr/lib/python3/dist-packages/mininet/clean.py`** to protect `ryu-manager` from accidental termination during `sudo mn -c`.
4. Creates a Python virtual environment at `~/sdn-venv` and installs all packages from [`requirements.txt`](requirements.txt).
5. Runs an import smoke test across `ryu`, `mininet`, `scapy`, `flask`, `matplotlib`, and `networkx`.

**🐧 Native WSL2 Terminal (Bash):**
```bash
chmod +x scripts/*.sh
./scripts/setup_env.sh
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "chmod +x scripts/*.sh && ./scripts/setup_env.sh"
```

🔍 **Crosscheck & Verification CLI:**
Verify that the `clean.py` patch was applied and virtual environment dependencies are present:

- **🐧 WSL Bash:**
  ```bash
  # 1. Verify Mininet clean.py patch (should output 0 matches):
  grep -c "'ryu-manager'" /usr/lib/python3/dist-packages/mininet/clean.py || echo "Patch Confirmed (0 matches)"
  
  # 2. Verify virtualenv packages:
  ~/sdn-venv/bin/pip list | grep -E "ryu|mininet|scapy|flask|matplotlib|networkx"
  
  # 3. Test core module imports:
  ~/sdn-venv/bin/python3 -c "import ryu, mininet, scapy, flask, matplotlib, networkx; print('All core modules verified!')"
  ```
- **🪟 PowerShell:**
  ```powershell
  # 1. Verify clean.py patch:
  wsl grep -c "'ryu-manager'" /usr/lib/python3/dist-packages/mininet/clean.py
  
  # 2. Verify virtualenv packages:
  wsl ~/sdn-venv/bin/pip list | Select-String -Pattern "ryu|mininet|scapy|flask|matplotlib|networkx"
  
  # 3. Test core module imports:
  wsl ~/sdn-venv/bin/python3 -c "import ryu, mininet, scapy, flask, matplotlib, networkx; print('All core modules verified!')"
  ```
- **Expected Output:**
  ```
  Patch Confirmed (0 matches)
  Flask       2.x+
  matplotlib  3.x+
  mininet     2.3.x+
  networkx    3.x+
  ryu         4.34+
  scapy       2.5.x+
  All core modules verified!
  ```

---

#### 1.4 Verify Open vSwitch Service Status
Ensure the Open vSwitch switch daemon is active and responsive:

**🐧 Native WSL2 Terminal (Bash):**
```bash
sudo service openvswitch-switch status
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -u root service openvswitch-switch status
```
*(If the service is stopped, start it via `sudo service openvswitch-switch start` or `wsl -u root service openvswitch-switch start`.)*

🔍 **Crosscheck & Verification CLI:**
Test local OVS database socket connectivity:

- **🐧 WSL Bash:**
  ```bash
  sudo ovs-vsctl show
  ```
- **🪟 PowerShell:**
  ```powershell
  wsl -u root ovs-vsctl show
  ```
- **Expected Output:** Prints the OVS configuration database UUID without any `database connection failed` error.

---

### 🧪 Step 2: Automated Pre-Flight Test Suite

Before launching interactive daemons, execute the automated test runner to verify core OpenFlow 1.3 pipeline mechanics.

The helper script [`./scripts/run_test.sh`](scripts/run_test.sh) is completely self-contained:
1. Resets stale OVS bridges and cleans Mininet state via `./scripts/cleanup.sh`.
2. Starts Ryu in the background on port `6653`.
3. Waits until port `6653` is actively accepting TCP connections.
4. Executes the target test suite under `sudo`.
5. Gracefully terminates Ryu and cleans up on completion.

#### 2.1 Run Test 1: VIP NAT & L2/L3 Bidirectional Rewriting
Verifies ARP resolution for VIP (`10.0.0.100`), reactive Flow-Mod installation, client-to-backend IP/MAC rewrite, and reverse translation.

**🐧 Native WSL2 Terminal (Bash):**
```bash
./scripts/run_test.sh tests/test_vip_rewrite.py
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "./scripts/run_test.sh tests/test_vip_rewrite.py"
```

🔍 **Crosscheck & Verification CLI:**
- **WSL Bash:** `echo "Test 1 Exit Code: $?"`
- **PowerShell:** `echo "Test 1 Exit Code: $LASTEXITCODE"`
- **Expected Output:** Console displays `*** All VIP NAT rewrite tests passed successfully! ***` and exit code `0`.

---

#### 2.2 Run Test 2: Multi-Algorithm Load Distribution
Validates request distribution and mathematical fairness for Round-Robin, Least-Connections, and Weighted (1:2:1:2) policies.

**🐧 Native WSL2 Terminal (Bash):**
```bash
./scripts/run_test.sh tests/test_lb_algorithms.py
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "./scripts/run_test.sh tests/test_lb_algorithms.py"
```

🔍 **Crosscheck & Verification CLI:**
- **WSL Bash:** `echo "Test 2 Exit Code: $?"`
- **PowerShell:** `echo "Test 2 Exit Code: $LASTEXITCODE"`
- **Expected Output:** Console displays `*** All load balancer distribution tests passed! ***` and exit code `0`.

---

#### 2.3 Run Test 3: Backend & Link Failover Recovery
Validates sub-second failover when a backend server goes down and adaptive rerouting when core links fail.

**🐧 Native WSL2 Terminal (Bash):**
```bash
./scripts/run_test.sh tests/test_failover.py
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "./scripts/run_test.sh tests/test_failover.py"
```

🔍 **Crosscheck & Verification CLI:**
- **WSL Bash:** `echo "Test 3 Exit Code: $?"`
- **PowerShell:** `echo "Test 3 Exit Code: $LASTEXITCODE"`
- **Expected Output:** Console displays `*** All failover tests passed! ***` and exit code `0`.

---

### 🚀 Step 3: Launching the Full Production Stack (Interactive End-to-End)

To observe real-time SDN load balancing, traffic engineering, and live web telemetry, open **four terminal tabs** (or background processes):

```mermaid
flowchart TD
    subgraph T1_Box ["🖥️ Terminal 1: Control Plane"]
        T1["<b>Ryu SDN Controller</b><br/>• OpenFlow 1.3 Server (:6653)<br/>• WSGI REST API (:8080)<br/>• LB, TE & Health Engines"]
    end

    subgraph T2_Box ["⚡ Terminal 2: Data Plane"]
        T2["<b>Mininet Diamond Topology</b><br/>• 4 OVS Switches (s1–s4)<br/>• 4 HTTP Backends (:80)<br/>• Client Hosts (h1, h2)"]
    end

    subgraph T3_Box ["📊 Terminal 3: Telemetry Console"]
        T3["<b>Live Operations Dashboard</b><br/>• Flask Web Service (:8081)<br/>• Real-Time Bandwidth & JFI Gauges<br/>• Browser: http://localhost:8081"]
    end

    subgraph T4_Box ["🕹️ Terminal 4: Host & Experimenter"]
        T4["<b>Experimenter Console / CLI</b><br/>• Client HTTP Probes (curl)<br/>• REST API Algorithm Toggles<br/>• Automated Benchmark Orchestrator"]
    end

    T1 <-->|"OpenFlow 1.3 (TCP 6653)<br/>Flow-Mod / Packet-In / Stats"| T2
    T3 -->|"REST Telemetry Polling<br/>(HTTP 8080 /api/telemetry)"| T1
    T4 -->|"REST Policy Updates<br/>(HTTP 8080 /api/algorithm)"| T1
    T4 -->|"Client HTTP Traffic<br/>(VIP: 10.0.0.100:80)"| T2
```

#### 3.1 Terminal 1: Launch Ryu SDN Controller
Starts the Ryu controller application on OpenFlow port `6653` and WSGI REST API on port `8080`:

**🐧 Native WSL2 Terminal (Bash):**
```bash
source ~/sdn-venv/bin/activate
ryu-manager controller/main.py --ofp-tcp-listen-port 6653
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "source ~/sdn-venv/bin/activate && ryu-manager controller/main.py --ofp-tcp-listen-port 6653"
```

*Expected startup logs:*
```
[INFO] Loading app controller.main
[INFO] [RyuApp] SDN Load Balancer & Traffic Engineering Controller Initializing...
[INFO] [RyuApp] VIP: 10.0.0.100 (00:00:00:00:00:fe), Port: 80
[INFO] (WSGI) serving on http://0.0.0.0:8080
```

🔍 **Crosscheck & Verification CLI (from Terminal 4 or PowerShell):**
Confirm Ryu is actively listening on both OpenFlow port 6653 and REST API port 8080:

- **🪟 PowerShell:**
  ```powershell
  Test-NetConnection -ComputerName 127.0.0.1 -Port 6653
  Test-NetConnection -ComputerName 127.0.0.1 -Port 8080
  Invoke-RestMethod -Uri "http://localhost:8080/api/stats"
  ```
- **🐧 WSL Bash:**
  ```bash
  ss -tulpn | grep -E "6653|8080"
  curl -s http://127.0.0.1:8080/api/stats | head -n 8
  ```
- **Expected Output:**
  `TcpTestSucceeded: True` for both ports, and REST returns JSON with `"algorithm": "round_robin"`.

---

#### 3.2 Terminal 2: Launch Mininet Diamond Mesh Topology
Cleans any stale network namespaces and starts the Mininet topology (4 OVS switches `s1`–`s4`, 2 clients `h1`–`h2`, and 4 backend servers `s1_srv`–`s4_srv`):

**🐧 Native WSL2 Terminal (Bash):**
```bash
sudo mn -c
sudo $(which python3) topology/lb_topology.py
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "sudo mn -c && sudo /home/$USER/sdn-venv/bin/python3 topology/lb_topology.py"
```

*Expected events:*
1. Terminal 2 displays the topology banner and enters the interactive `mininet>` prompt.
2. Terminal 1 logs switch handshakes: `[Switch s1-s4 connected] Table-miss flow installed`.
3. 4 background Flask HTTP backend servers are automatically spawned on `10.0.0.11`–`10.0.0.14:80`.

> **Note (Headless / Daemon Mode):** If you wish to run Mininet in daemon mode without an interactive CLI, pass `--no-cli`:
> ```powershell
> wsl -e bash -c "sudo /home/$USER/sdn-venv/bin/python3 topology/lb_topology.py --no-cli"
> ```

🔍 **Crosscheck & Verification CLI (from Terminal 4 or PowerShell):**
Confirm that OVS switches are connected to Ryu and backend servers are running:

- **Check Switch OpenFlow Connection to Controller:**
  - **🪟 PowerShell:** `wsl -u root ovs-vsctl get Bridge s1 is_connected`
  - **🐧 WSL Bash:** `sudo ovs-vsctl get Bridge s1 is_connected`
  - **Expected Output:** `true`
- **Check Backend HTTP Server Processes:**
  - **🪟 PowerShell:** `wsl pgrep -a -f "backend_server.py"`
  - **🐧 WSL Bash:** `pgrep -a -f "backend_server.py"`
  - **Expected Output:** 4 processes running (one for each server `s1_srv` through `s4_srv`).

---

#### 3.3 Terminal 3: Launch Live Telemetry Web Dashboard
Starts the real-time Flask operations console on port `8081`:

**🐧 Native WSL2 Terminal (Bash):**
```bash
source ~/sdn-venv/bin/activate
python3 dashboard/live_dashboard.py
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "source ~/sdn-venv/bin/activate && python3 dashboard/live_dashboard.py"
```

*Accessing the Dashboard:*
Open your web browser on Windows (Chrome, Edge, Firefox) and navigate to:
👉 **`http://localhost:8081`**

🔍 **Crosscheck & Verification CLI:**
Confirm the dashboard web service is listening and serving requests:

- **🪟 PowerShell:**
  ```powershell
  Test-NetConnection -ComputerName 127.0.0.1 -Port 8081
  (Invoke-WebRequest -Uri "http://localhost:8081/").StatusCode
  ```
- **🐧 WSL Bash:**
  ```bash
  curl -sI http://localhost:8081/ | head -n 1
  ```
- **Expected Output:** `TcpTestSucceeded: True` and HTTP status code `200`.

---

### 🕹️ Step 4: Live Probing, Testing & Dynamic Control (Terminal 4)

With the platform running, open a fourth terminal (or use the Mininet CLI in Terminal 2) to probe the data plane and interact with the controller.

#### 4.1 Dispatch HTTP Requests from Mininet Host (`h1`)
From the Mininet CLI in Terminal 2:

```bash
# Send a single request to the Virtual IP
mininet> h1 curl -s http://10.0.0.100/

# Dispatch a batch of 8 requests to observe load balancing across backends
mininet> h1 for i in {1..8}; do curl -s http://10.0.0.100/; echo ""; done

# Verify ICMP connectivity and baseline round-trip time
mininet> h1 ping -c 3 10.0.0.100
```

🔍 **Crosscheck & Verification:**
- Each curl command returns a JSON response identifying the handling backend:
  `{"client": "10.0.0.1", "request_count": 1, "server_id": "srv1"}`
- In a loop of 8 requests under Round-Robin, responses cycle uniformly: `srv1` $\to$ `srv2` $\to$ `srv3` $\to$ `srv4` $\to$ `srv1`...

---

#### 4.2 Inspect OpenFlow 1.3 Flow Tables
Inspect the flow table rules installed reactively by Ryu on the ingress switch (`s1`):

**🐧 Native WSL2 Terminal (Bash):**
```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -u root ovs-ofctl -O OpenFlow13 dump-flows s1
```

🔍 **Crosscheck & Verification:**
Confirm the presence of reactive flow entries with packet and byte increments:
- **Priority 50 (Forward NAT):** Matches `nw_dst=10.0.0.100`, rewrites `mod_dl_dst`, `mod_nw_dst`, and outputs to transit port.
- **Priority 40 (Reverse NAT):** Matches `nw_src=10.0.0.1X`, rewrites `mod_dl_src`, `mod_nw_src=10.0.0.100`, and returns packet to client.
- **`n_packets` and `n_bytes`:** Must be greater than 0, verifying hardware/kernel forwarding hit counts.

---

#### 4.3 Query Real-Time Telemetry via REST API
Query the Ryu REST API (`port 8080`) directly from Windows PowerShell:

**🪟 Windows PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8080/api/telemetry" | ConvertTo-Json -Depth 4
```

**🐧 Native WSL2 Terminal (Bash):**
```bash
curl -s http://localhost:8080/api/telemetry | jq .
```

🔍 **Crosscheck & Verification:**
Verify that `link_utilization` contains byte rates for Upper Path A and Lower Path B, and `active_connections` reflects currently active flows.

---

#### 4.4 Dynamically Switch Load Balancing Algorithms at Runtime
Switch algorithms on-the-fly without restarting controller or switches:

**Switch to Least-Connections:**
- **🪟 PowerShell:**
  ```powershell
  Invoke-RestMethod -Uri "http://localhost:8080/api/algorithm" -Method Post -ContentType "application/json" -Body '{"algorithm": "least_connections"}'
  ```
- **🐧 WSL Bash:**
  ```bash
  curl -X POST http://localhost:8080/api/algorithm -H "Content-Type: application/json" -d '{"algorithm": "least_connections"}'
  ```

**Switch to Weighted Load Balancing (1:2:1:2):**
- **🪟 PowerShell:**
  ```powershell
  Invoke-RestMethod -Uri "http://localhost:8080/api/algorithm" -Method Post -ContentType "application/json" -Body '{"algorithm": "weighted"}'
  ```
- **🐧 WSL Bash:**
  ```bash
  curl -X POST http://localhost:8080/api/algorithm -H "Content-Type: application/json" -d '{"algorithm": "weighted"}'
  ```

🔍 **Crosscheck & Verification CLI:**
Confirm that the active algorithm updated on the controller:
- **PowerShell:** `(Invoke-RestMethod http://localhost:8080/api/stats).algorithm`
- **WSL Bash:** `curl -s http://localhost:8080/api/stats | grep '"algorithm"'`
- **Expected Output:** Confirms `"least_connections"` or `"weighted"`.

---

#### 4.5 Simulate Backend Server Failure & Sub-Second Failover
Mark backend `srv1` (`10.0.0.11`) as DOWN via the REST API to trigger active failover:

**🪟 Windows PowerShell:**
```powershell
# Take srv1 offline:
Invoke-RestMethod -Uri "http://localhost:8080/api/backend/health" -Method Post -ContentType "application/json" -Body '{"backend_id": 0, "healthy": false}'
```

**🐧 Native WSL2 Terminal (Bash):**
```bash
# Take srv1 offline:
curl -X POST http://localhost:8080/api/backend/health -H "Content-Type: application/json" -d '{"backend_id": 0, "healthy": false}'
```

🔍 **Crosscheck & Verification CLI:**
1. **Verify Health State:**
   - **PowerShell:** `(Invoke-RestMethod http://localhost:8080/api/stats).backends[0].healthy`
   - **Expected Output:** `False`
2. **Verify Failover on Dashboard:** The indicator for `srv1` changes to **DEAD** (red).
3. **Dispatch Verification Requests:** From Mininet CLI:
   ```bash
   mininet> h1 for i in {1..6}; do curl -s http://10.0.0.100/; echo ""; done
   ```
   All requests are distributed exclusively among healthy backends (`srv2`, `srv3`, `srv4`) with **0% request failure**!
4. **Restore `srv1` back online:**
   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8080/api/backend/health" -Method Post -ContentType "application/json" -Body '{"backend_id": 0, "healthy": true}'
   ```
   Confirm `(Invoke-RestMethod http://localhost:8080/api/stats).backends[0].healthy` returns `True`.

---

#### 4.6 Simulate Traffic Congestion & Adaptive Rerouting
Generate high-concurrency traffic to Upper Path A using [`benchmark/generate_load.py`](benchmark/generate_load.py):

**🐧 Native WSL2 Terminal (Bash):**
```bash
source ~/sdn-venv/bin/activate
python3 benchmark/generate_load.py --requests 60 --concurrency 6
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "source ~/sdn-venv/bin/activate && python3 benchmark/generate_load.py --requests 60 --concurrency 6"
```

🔍 **Crosscheck & Verification CLI:**
Query traffic engineering state during/after high-load injection:

- **🪟 PowerShell:**
  ```powershell
  (Invoke-RestMethod -Uri "http://localhost:8080/api/telemetry").traffic_engineering
  ```
- **🐧 WSL Bash:**
  ```bash
  curl -s http://localhost:8080/api/telemetry | jq .traffic_engineering
  ```
- **Expected Output:**
  Displays `active_path`, `path_a_utilization`, `path_b_utilization`, and `last_reason` indicating rerouting or primary restoration.
- **Terminal 1 Log Check:** Terminal 1 prints `[TE] *** ADAPTIVE REROUTING TRIGGERED *** Congestion on Path A. Rerouted to Path B.`

---

### 📊 Step 5: Full Benchmark Suite & Scientific Chart Generation

To run the full comparative benchmark (72 requests per algorithm, measuring RPS, Latency CDF, and Jain's Fairness Index) and automatically generate publication-ready plots:

#### 5.1 Run Automated Benchmark Orchestrator
Ensure Ryu controller is running in Terminal 1, then execute:

**🐧 Native WSL2 Terminal (Bash):**
```bash
sudo mn -c
sudo /home/$USER/sdn-venv/bin/python3 benchmark/run_all_benchmarks.py
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "sudo mn -c && sudo /home/$USER/sdn-venv/bin/python3 benchmark/run_all_benchmarks.py"
```

🔍 **Crosscheck & Verification CLI:**
Confirm that benchmark evaluation records were calculated and saved to JSON:

- **🪟 PowerShell:**
  ```powershell
  wsl cat benchmark/results/summary_metrics.json | Select-String -Pattern "jains_fairness_index|throughput_rps"
  ```
- **🐧 WSL Bash:**
  ```bash
  python3 -c "import json; d=json.load(open('benchmark/results/summary_metrics.json')); [print(f'[{k.upper()}] JFI: {v[\"jains_fairness_index\"]}, RPS: {v[\"throughput_rps\"]}') for k,v in d.items()]"
  ```
- **Expected Output:**
  ```
  [ROUND_ROBIN] JFI: 1.0, RPS: 32.13
  [LEAST_CONNECTIONS] JFI: 1.0, RPS: 29.53
  [WEIGHTED] JFI: 1.0, RPS: 28.91
  ```

---

#### 5.2 Standalone Plot Regeneration
To re-generate all scientific figures from existing benchmark data at any time:

**🐧 Native WSL2 Terminal (Bash):**
```bash
source ~/sdn-venv/bin/activate
python3 dashboard/plot_results.py
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "source ~/sdn-venv/bin/activate && python3 dashboard/plot_results.py"
```

🔍 **Crosscheck & Verification CLI:**
Verify that all 4 scientific comparison figures have been generated and are non-empty:

- **🪟 PowerShell:**
  ```powershell
  Get-ChildItem figures\*.png | Select-Object Name, Length, LastWriteTime
  ```
- **🐧 WSL Bash:**
  ```bash
  ls -lh figures/*.png
  ```
- **Expected Output:** All 4 plot files (`load_distribution_comparison.png`, `latency_cdf.png`, `throughput_comparison.png`, `fairness_index_comparison.png`) are present with file sizes > 50 KB.

#### 5.3 View Generated Figures in Windows Explorer
From Windows PowerShell, open the generated figures directory directly in Windows File Explorer:
```powershell
explorer.exe figures
```

---

### 🧹 Step 6: Teardown & Environment Cleanup

When testing is finished, execute [`./scripts/cleanup.sh`](scripts/cleanup.sh) to cleanly terminate all background controller processes, backend HTTP servers, telemetry threads, and purge Mininet namespaces and lingering OVS bridges:

**🐧 Native WSL2 Terminal (Bash):**
```bash
./scripts/cleanup.sh
```

**🪟 Windows PowerShell (`wsl`):**
```powershell
wsl -e bash -c "./scripts/cleanup.sh"
```

🔍 **Crosscheck & Verification CLI:**
Perform post-cleanup verification to confirm a pristine state:

1. **Verify No Dangling OVS Bridges:**
   - **PowerShell:** `wsl -u root ovs-vsctl list-br`
   - **WSL Bash:** `sudo ovs-vsctl list-br`
   - **Expected Output:** Empty (no output).
2. **Verify No Background Python / SDN Processes:**
   - **PowerShell:** `wsl pgrep -a -f "ryu-manager|backend_server|live_dashboard|mininet"`
   - **WSL Bash:** `pgrep -a -f "ryu-manager|backend_server|live_dashboard|mininet"`
   - **Expected Output:** Empty (no processes found).
3. **Verify TCP Ports are Released:**
   - **PowerShell:**
     ```powershell
     Test-NetConnection -ComputerName 127.0.0.1 -Port 6653
     Test-NetConnection -ComputerName 127.0.0.1 -Port 8080
     Test-NetConnection -ComputerName 127.0.0.1 -Port 8081
     ```
   - **Expected Output:** `TcpTestSucceeded: False` for all three ports.

---

### ❓ Step 7: Troubleshooting & Common WSL2 Pitfalls FAQ

#### Q1: `ovs-vsctl: unix:/var/run/openvswitch/db.sock: database connection failed`
- **Cause:** In WSL2, background services do not automatically start on boot unless configured via systemd.
- **Fix:** Start the Open vSwitch daemon manually:
  ```powershell
  wsl -u root service openvswitch-switch start
  ```

#### Q2: `sudo mn -c` terminates my Ryu controller instance!
- **Cause:** Stock Mininet's `/usr/lib/python3/dist-packages/mininet/clean.py` contains `'ryu-manager'` in its `killprocs` list.
- **Fix:** Run `./scripts/setup_env.sh`, which automatically removes `'ryu-manager'` from `clean.py`. Alternatively, run this one-liner:
  ```powershell
  wsl -u root sed -i "s/'ryu-manager'//g" /usr/lib/python3/dist-packages/mininet/clean.py
  ```

#### Q3: `ModuleNotFoundError` when running Mininet with `sudo`
- **Cause:** Running `sudo python3` invokes the root system Python (`/usr/bin/python3`) rather than your virtual environment where Ryu and Scapy are installed.
- **Fix:** Use the full virtual environment Python binary path:
  ```powershell
  wsl -e bash -c "sudo /home/$USER/sdn-venv/bin/python3 topology/lb_topology.py"
  ```
  *(Or in WSL bash: `sudo $(which python3) topology/lb_topology.py` after activating the virtual environment).*

#### Q4: Cannot open Web Dashboard (`http://localhost:8081`) from Windows browser
- **Cause:** WSL2 networking mode or local firewall is blocking port forwarding.
- **Fix:**
  1. Verify the dashboard is running: `wsl -e curl -s http://127.0.0.1:8081/api/stats`
  2. If Windows cannot connect to `localhost:8081`, get the WSL2 internal IP:
     ```powershell
     wsl hostname -I
     ```
     Navigate in your Windows browser to `http://<WSL_IP>:8081`.

#### Q5: Address already in use (`Errno 98` on port 6653, 8080, or 8081)
- **Cause:** A previous instance of Ryu, Flask, or Mininet was interrupted before releasing its TCP socket.
- **Fix:** Kill lingering processes listening on these ports:
  ```powershell
  wsl -u root fuser -k 6653/tcp 8080/tcp 8081/tcp
  wsl -e bash -c "./scripts/cleanup.sh"
  ```



