# System Architecture Specification

## OpenFlow 1.3 SDN-Based Load Balancer & Adaptive Traffic Engineering System

---

## 1. Architectural Overview

This system replaces traditional hardware application delivery controllers (ADCs) by decoupling control and data planes through OpenFlow 1.3. The control plane, implemented using the **Ryu SDN Framework**, manages physical forwarding topology, dynamic load balancing, health monitoring, and traffic engineering. The data plane is executed on **Open vSwitch (OVS)** inside a Mininet-emulated network environment.

```mermaid
graph TD
    subgraph ManagementPlane ["Management & Telemetry Plane"]
        Dashboard["Live Web Dashboard<br/>(Flask :8081)"]
        Benchmarks["Benchmarking Suite<br/>(curl / iperf3 / Scapy)"]
        REST["Ryu REST API<br/>(:8080/api)"]
    end

    subgraph ControlPlane ["Ryu SDN Controller (OpenFlow 1.3)"]
        MainApp["Main Controller App<br/>(main.py)"]
        FlowMgr["Flow Manager<br/>(flow_manager.py)"]
        LB["Load Balancer Engine<br/>(load_balancer.py)"]
        TopoDisc["Topology Discovery<br/>(topology_discovery.py)"]
        StatsMon["Stats Monitor<br/>(stats_monitor.py)"]
        HealthCheck["Health Checker<br/>(health_checker.py)"]
        TrafficEng["Traffic Engineer<br/>(traffic_engineer.py)"]

        MainApp --> FlowMgr
        MainApp --> LB
        MainApp --> TopoDisc
        MainApp --> StatsMon
        MainApp --> HealthCheck
        MainApp --> TrafficEng
    end

    subgraph DataPlane ["Data Plane (Open vSwitch / Mininet)"]
        subgraph Clients
            H1["Client h1<br/>10.0.0.1"]
            H2["Client h2<br/>10.0.0.2"]
        end

        S1["Ingress Switch (s1)<br/>dpid: 1"]
        S2["Transit Path A (s2)<br/>dpid: 2 (Primary)"]
        S3["Transit Path B (s3)<br/>dpid: 3 (Alternate)"]
        S4["Egress Switch (s4)<br/>dpid: 4"]

        subgraph Backends ["Backend Server Farm"]
            Srv1["srv1 (10.0.0.11)<br/>Weight: 1"]
            Srv2["srv2 (10.0.0.12)<br/>Weight: 2"]
            Srv3["srv3 (10.0.0.13)<br/>Weight: 1"]
            Srv4["srv4 (10.0.0.14)<br/>Weight: 2"]
        end
    end

    Dashboard -->|HTTP REST| REST
    Benchmarks -->|Traffic Load| H1
    Benchmarks -->|Traffic Load| H2
    REST --> MainApp

    ControlPlane <==|OpenFlow 1.3 (TCP 6653)|==> S1
    ControlPlane <==|OpenFlow 1.3 (TCP 6653)|==> S2
    ControlPlane <==|OpenFlow 1.3 (TCP 6653)|==> S3
    ControlPlane <==|OpenFlow 1.3 (TCP 6653)|==> S4

    H1 --- S1
    H2 --- S1
    S1 ---|Port 2 / 10 Mbps| S2
    S1 ---|Port 3 / 10 Mbps| S3
    S2 ---|Port 2 / 10 Mbps| S4
    S3 ---|Port 2 / 10 Mbps| S4
    S4 --- Srv1
    S4 --- Srv2
    S4 --- Srv3
    S4 --- Srv4
```

---

## 2. Decoupling the Control and Data Planes

Traditional load balancers (e.g., F5 BIG-IP, Citrix ADC) combine packet inspection, state tracking, and packet rewriting into proprietary hardware appliances. This project achieves complete separation:

1. **Data Plane (Open vSwitch):**
   - High-throughput flow processing without connection state machines.
   - Executes OpenFlow 1.3 actions: `SET_FIELD` (`ipv4_dst`, `eth_dst`, `ipv4_src`, `eth_src`), `OUTPUT`, `DROP`.
   - Forwarding state is governed strictly by the flow tables programmed by Ryu.
   - Operates in secure mode (`fail_mode=secure`), ensuring switches drop or buffer unhandled packets rather than falling back to traditional legacy flooding.

2. **Control Plane (Ryu Controller):**
   - Centralized intelligence running on Python 3.
   - Dynamic server selection algorithms (Round-Robin, Least-Connections, Weighted).
   - Link telemetry collection via asynchronous OpenFlow multi-part stats (`OFPPortStatsRequest`).
   - Active Layer 7 application health verification via periodic HTTP probing.
   - Dynamic path recomputation and proactive flow installation during link saturation or failures.

3. **Southbound Protocol (OpenFlow 1.3):**
   - Standardized binary wire protocol operating over TCP port 6653.
   - Message types utilized:
     - `OFPT_HELLO`: Protocol version negotiation (OpenFlow 1.3, `0x04`).
     - `OFPT_FEATURES_REQUEST` / `OFPT_FEATURES_REPLY`: Switch datapath capabilities exchange.
     - `OFPT_FLOW_MOD`: Proactive and reactive flow table installations, modifications, and removals.
     - `OFPT_PACKET_IN`: Data plane miss redirection to controller logic.
     - `OFPT_PACKET_OUT`: Controller-generated packets injected into the data plane (e.g., Proxy ARP).
     - `OFPT_MULTIPART_REQUEST` / `REPLY`: Statistics telemetry polling (Port and Flow statistics).
     - `OFPT_PORT_STATUS`: Asynchronous link status updates (e.g., interface down/up detection).

---

## 3. OpenFlow Flow Table Pipeline & Priority Hierarchy

To avoid packet ambiguity and race conditions, the single-table and multi-pipeline flow matches adhere to an explicit priority hierarchy:

| Priority | Purpose | Match Conditions | Actions | Timeouts |
|---|---|---|---|---|
| **100** | Health Check & Management Bypass | `eth_type=0x0800, ip_proto=6, tcp_dst=80, ipv4_dst={10.0.0.11-14}` | `OUTPUT:port` (Direct forwarding without NAT translation) | `idle=0, hard=0` |
| **50** | Forward VIP NAT (Client $\rightarrow$ Server) | `eth_type=0x0800, ip_proto=6, ipv4_src=client_ip, ipv4_dst=10.0.0.100, tcp_dst=80` | `SET_FIELD(ipv4_dst=srv_ip)`, `SET_FIELD(eth_dst=srv_mac)`, `OUTPUT:transit_port` | `idle=15, hard=60` |
| **40** | Reverse VIP NAT (Server $\rightarrow$ Client) | `eth_type=0x0800, ip_proto=6, ipv4_src=srv_ip, ipv4_dst=client_ip, tcp_src=80` | `SET_FIELD(ipv4_src=10.0.0.100)`, `SET_FIELD(eth_src=vip_mac)`, `OUTPUT:client_port` | `idle=15, hard=60` |
| **30** | Proxy ARP Handling | `eth_type=0x0806, arp_tpa=10.0.0.100` | Controller Packet-In / Direct Controller ARP Reply | `idle=0, hard=0` |
| **20** | Traffic Engineering Rerouting | Link-specific forwarding rules | Forward to alternate path (Path B instead of Path A) | `idle=30, hard=120` |
| **10** | Standard Unicast L2/L3 Forwarding | `eth_dst=host_mac` | `OUTPUT:host_port` | `idle=30, hard=60` |
| **0** | Default Table-Miss | `match=*` | `OUTPUT:OFPP_CONTROLLER` (Buffer: `OFPCML_NO_BUFFER`) | Permanent |

---

## 4. End-to-End Packet Walkthrough: Bidirectional NAT Rewriting

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client (10.0.0.1)
    participant S1 as Ingress Switch (s1)
    participant Ryu as Ryu Controller
    participant S2 as Transit Switch (s2)
    participant S4 as Egress Switch (s4)
    participant Server as Backend Server (10.0.0.12)

    Note over Client,Ryu: Step 1: Virtual IP ARP Resolution
    Client->>S1: ARP Request: Who has 10.0.0.100?
    S1->>Ryu: OFPT_PACKET_IN (ARP Request)
    Ryu->>S1: OFPT_PACKET_OUT (ARP Reply: 10.0.0.100 is at 00:00:00:00:00:fe)
    S1->>Client: ARP Reply: 10.0.0.100 is at 00:00:00:00:00:fe

    Note over Client,Server: Step 2: TCP Connection Initiation (SYN)
    Client->>S1: IP Pkt: src=10.0.0.1, dst=10.0.0.100, tcp_dst=80 [SYN]
    S1->>Ryu: OFPT_PACKET_IN (Match: Priority 0 Table-Miss)
    Note over Ryu: Select Backend: srv2 (10.0.0.12)<br/>Select Path: Path A (s1 -> s2 -> s4)
    
    Ryu->>S1: OFPT_FLOW_MOD (Priority 50: dst=10.0.0.100:80 -> SET dst=10.0.0.12, OUT:s2)
    Ryu->>S4: OFPT_FLOW_MOD (Priority 40: src=10.0.0.12:80 -> SET src=10.0.0.100, OUT:s2)
    Ryu->>S2: OFPT_FLOW_MOD (Priority 10: Bidirectional Transit Forwarding)
    Ryu->>S1: OFPT_PACKET_OUT (Forward SYN along Path A)

    S1->>S2: Rewritten Pkt: src=10.0.0.1, dst=10.0.0.12
    S2->>S4: Transit Forward
    S4->>Server: Delivered Pkt: src=10.0.0.1, dst=10.0.0.12 [SYN]

    Note over Server,Client: Step 3: TCP SYN-ACK Response
    Server->>S4: IP Pkt: src=10.0.0.12, dst=10.0.0.1, tcp_src=80 [SYN-ACK]
    Note over S4: Matched Priority 40 Flow Rule<br/>SET ipv4_src=10.0.0.100<br/>SET eth_src=00:00:00:00:00:fe
    S4->>S2: Rewritten Pkt: src=10.0.0.100, dst=10.0.0.1
    S2->>S1: Transit Forward
    S1->>Client: Delivered Pkt: src=10.0.0.100, dst=10.0.0.1 [SYN-ACK]

    Note over Client,Server: Step 4: Line-Rate Forwarding (Direct Data Plane)
    Client->>S1: TCP ACK / HTTP GET request
    Note over S1,S4: Hardware/Kernel processing via installed flows (0ms controller overhead)
    S1->>S2: Forwarded
    S2->>S4: Forwarded
    S4->>Server: Received HTTP GET
    Server->>S4: HTTP 200 Response
    S4->>S2: Rewritten to VIP
    S2->>S1: Forwarded
    S1->>Client: Received HTTP 200
```

---

## 5. Resilience & High-Availability Architecture

1. **Active Probing (`HealthChecker`):**
   - Continuously performs non-blocking HTTP health checks to each backend instance (`/health`).
   - If an instance fails consecutive checks (configured limit: 2 failures), the controller removes the node from active load balancing scheduling.
   - Any active flows targeting the failed node are proactively deleted via `OFPFC_DELETE` to trigger immediate re-selection on subsequent packets.
   - When the backend recovers (1 successful response), it is restored to the pool automatically.

2. **Adaptive Traffic Engineering (`TrafficEngineer`):**
   - Periodically queries switch port stats (`OFPPortStatsRequest`).
   - Computes delta transmit/receive bytes over polling interval $\Delta t$:
     $$\text{Throughput (bps)} = \frac{(B_t - B_{t-\Delta t}) \times 8}{\Delta t}$$
     $$\text{Utilization (\%)} = \frac{\text{Throughput}}{\text{Link Capacity (10 Mbps)}} \times 100$$
   - When the primary transit path ($s1 \leftrightarrow s2 \leftrightarrow s4$) exceeds 75% link capacity, the controller redirects new and elephant flows across the alternate path ($s1 \leftrightarrow s3 \leftrightarrow s4$).
