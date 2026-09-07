# SDN Capstone Project: Task Tracker & Milestones

**Project:** OpenFlow 1.3 SDN-Based Load Balancer and Adaptive Traffic Engineering System  
**Timeline:** 4-Month Academic Capstone (CPMK-1, CPMK-2, CPMK-3, CPMK-4, CPMK-5)

---

## Progress Overview

| Phase | Description | Status | Evidence / Tag |
|---|---|---|---|
| **Phase 0** | Workspace Reset & Scaffolding | `[x]` Completed | `v0.0-scaffold` |
| **Phase 1** | Topology, Environment & Backend Microservice | `[x]` Completed | `v0.1-env-scaffold` |
| **Phase 2** | Core SDN Load Balancer (RR, LC, Weighted) | `[x]` Completed | `v0.2-load-balancer` |
| **Phase 3** | Telemetry, Health Probing & Traffic Engineering | `[/]` In Progress | `v0.3-monitoring` |
| **Phase 4** | Benchmarking Suite, Evaluation & Failover | `[ ]` Pending | `v0.4-benchmarks` |
| **Phase 5** | Live Web Dashboard, Documentation & CPMK Report | `[ ]` Pending | `v1.0-release` |

---

## Detailed Task Breakdown

### Phase 0: Workspace Reset & Scaffolding `[x]`
- [x] Clean old codebase and files from `e:\Projects\sdn-project`
- [x] Initialize clean git repository
- [x] Recreate `GEMINI.md` with new Capstone guidelines and CPMK mapping
- [x] Recreate `.agents/rules/sdn-capstone.md` and `.agents/skills/sdn-capstone-mentor/SKILL.md`
- [x] Setup directory structure (`topology`, `controller`, `server`, `benchmark`, `tests`, `scripts`, `dashboard`, `figures`, `docs`)
- [x] Add `.gitignore`, `requirements.txt`, and `README.md`

### Phase 1: Topology, Environment & Backend Microservice `[x]`
- [x] Create `scripts/setup_env.sh` to verify WSL2 dependencies in `/home/rafli_alif/sdn-venv`
- [x] Create `scripts/cleanup.sh` for reliable Mininet/OVS cleanup
- [x] Implement `topology/lb_topology.py`:
  - 2+ switches with redundant/multi-path links (TCLink `bw=10`, `delay=2ms`)
  - 2 client hosts (`h1`, `h2`)
  - 4 backend server hosts (`s1_srv` to `s4_srv`)
  - OpenFlow 1.3 enforcement on all bridges
- [x] Implement `server/backend_server.py`:
  - Flask HTTP server returning JSON `{ "server_id": id, "request_count": count, "timestamp": ts }`
  - Health check endpoint `/health` returning HTTP 200

### Phase 2: Core SDN Load Balancer (Month 1–2) `[x]`
- [x] Implement `controller/config.py`:
  - VIP address (`10.0.0.100`), Virtual MAC (`00:00:00:00:00:fe`), service port `80`
  - Backend pool specification (IPs, MACs, physical switch ports)
  - Timeouts and priority constants
- [x] Implement `controller/flow_manager.py`:
  - OFP 1.3 Flow-Mod installation helper (actions, match, timeouts, priorities)
  - Group table and bucket installation utilities
- [x] Implement `controller/main.py`:
  - `EventOFPSwitchFeatures`: Table-Miss flow installation (`priority=0`)
  - `EventOFPPacketIn`: Proxy ARP handling and TCP handshake delegation
- [x] Implement `controller/load_balancer.py`:
  - ARP responder for VIP requests (reply with Virtual MAC)
  - Bidirectional NAT rewriting (Client -> VIP rewritten to Backend; Backend -> Client rewritten to VIP)
  - Algorithm 1: **Round-Robin**
  - Algorithm 2: **Least-Connections** (using active flow counts)
  - Algorithm 3: **Weighted / Utilization-Aware**
- [x] Verification:
  - `tests/test_vip_rewrite.py`: Verify NAT flow rules and HTTP responses (PASSED)
  - `tests/test_lb_algorithms.py`: Validate traffic distribution ratios (PASSED)

### Phase 3: Telemetry, Health Probing & Traffic Engineering (Month 2–3) `[ ]`
- [ ] Implement `controller/stats_monitor.py`:
  - Periodic `OFPPortStatsRequest` (every 5s) to track port bytes and bandwidth
  - Periodic `OFPFlowStatsRequest` to track active connections per backend
  - Ryu WSGI REST endpoints for telemetry data export
- [ ] Implement `controller/health_checker.py`:
  - Periodic TCP/HTTP probing of backend `/health` endpoint
  - Automatic marking of DOWN backends after consecutive timeouts
  - Seamless pool removal and recovery
- [ ] Implement `controller/traffic_engineer.py`:
  - Dynamic link utilization threshold detection (e.g. > 80% capacity)
  - Path computation across topology redundant links
  - Installation of alternate path flows (implicitly covering CPMK-4)
- [ ] Verification:
  - Verify stats accuracy during traffic bursts
  - Verify server failure removal and failover

### Phase 4: Benchmarking Suite, Evaluation & Failover (Month 3) `[ ]`
- [ ] Implement `benchmark/generate_load.py`:
  - Configurable concurrent HTTP request generator
  - Latency, status code, and target backend tracking
- [ ] Implement `benchmark/measure_fairness.py`:
  - Calculate Jain's Fairness Index for each algorithm
- [ ] Implement `benchmark/iperf_bench.sh`:
  - Automated multi-stream throughput testing
- [ ] Implement `benchmark/run_all_benchmarks.py`:
  - Automated benchmark orchestrator producing CSV/JSON outputs
- [ ] Implement `tests/test_failover.py`:
  - Test backend crash failover time
  - Test link failure recovery time
- [ ] Implement `dashboard/plot_results.py`:
  - Generate load distribution bar charts
  - Generate latency vs throughput curves
  - Generate Jain's Fairness comparison figures

### Phase 5: Live Dashboard, Documentation & CPMK Report (Month 4) `[ ]`
- [ ] Implement `dashboard/live_dashboard.py`:
  - Flask web app visualizing real-time backend load, link utilization, and server health
- [ ] Write `docs/architecture.md`:
  - System architecture diagram (Mermaid)
  - Flow table priority hierarchy and OpenFlow pipeline specification
- [ ] Write `docs/algorithms.md`:
  - Comparative analysis of RR, LC, and Weighted/Utilization-Aware algorithms
- [ ] Write `docs/cpmk_mapping.md`:
  - Mapping of all features to CPMK-1, CPMK-2, CPMK-3, CPMK-4, and CPMK-5
- [ ] Write `docs/final_report.md`:
  - Complete academic capstone report
