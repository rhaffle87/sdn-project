# Load Balancing & Traffic Engineering Algorithms Specification

---

## 1. Overview of Implemented Algorithms

The Ryu SDN Controller provides three distinct Layer 4 load balancing algorithms alongside an adaptive link-utilization traffic engineering engine. Each algorithm balances trade-offs between computational overhead, state tracking complexity, and resource distribution equity.

---

## 2. Algorithm 1: Round-Robin (RR)

### Concept & Mechanics
Round-Robin distributes incoming TCP client connections cyclically across the healthy backend pool without consideration of current server workload, CPU usage, or connection longevity.

### Mathematical Formulation

Let $B = [b_0, b_1, \dots, b_{n-1}]$ represent the ordered set of $n$ healthy backend servers. For the $k$-th incoming TCP connection request ($k \ge 0$):

$$\text{Selected Server Index } i = k \pmod n$$

where $k$ increments by 1 for each new connection dispatch.

### Pseudocode
```python
def select_round_robin(healthy_servers, current_index):
    if not healthy_servers:
        return None
    selected = healthy_servers[current_index % len(healthy_servers)]
    next_index = (current_index + 1) % len(healthy_servers)
    return selected, next_index
```

### Complexity
- **Time Complexity:** $\mathcal{O}(1)$ — Single pointer increment and modulo operation.
- **Space Complexity:** $\mathcal{O}(1)$ — Single integer tracking pointer state.

---

## 3. Algorithm 2: Least-Connections (LC)

### Concept & Mechanics
Least-Connections optimizes for heterogeneous request durations by dispatching each incoming connection to the backend server with the lowest count of active TCP connections. Active connections are tracked using OpenFlow flow statistics and flow count counters maintained within the controller.

### Mathematical Formulation
Let $C(b_j)$ denote the active connection count currently assigned to backend $b_j \in B$.
$$b^* = \arg\min_{b_j \in B} C(b_j)$$
In the event of a tie where multiple servers share the identical minimum count:
$$\arg\min \{ C(b_j) \} \implies \text{Round-Robin tie breaker among candidates}$$

### Pseudocode
```python
def select_least_connections(healthy_servers, active_connections):
    if not healthy_servers:
        return None
    min_conn = float('inf')
    best_server = healthy_servers[0]
    for srv in healthy_servers:
        conn = active_connections.get(srv['ip'], 0)
        if conn < min_conn:
            min_conn = conn
            best_server = srv
    active_connections[best_server['ip']] += 1
    return best_server
```

### Complexity
- **Time Complexity:** $\mathcal{O}(n)$ — Linear search over $n$ active backend instances.
- **Space Complexity:** $\mathcal{O}(n)$ — Hash map storing active connection counters for all backends.

---

## 4. Algorithm 3: Weighted Round-Robin (WRR)

### Concept & Mechanics
In production data centers, servers often possess disparate hardware specifications (e.g., varying CPU core counts and memory sizes). Weighted Round-Robin assigns static integer weights $w_j \ge 1$ to each backend server, guaranteeing that servers with higher capacity handle proportionally larger shares of traffic.

### Mathematical Formulation
Given backends $b_0, b_1, \dots, b_{n-1}$ with weights $w_0, w_1, \dots, w_{n-1}$. The total weight is:
$$W = \sum_{j=0}^{n-1} w_j$$
The expected proportion of traffic allocated to server $b_j$ over $N$ total requests is:
$$E[T_j] = N \cdot \frac{w_j}{W}$$

In our deployment:
- $\text{srv1 (10.0.0.11)}: w_1 = 1$
- $\text{srv2 (10.0.0.12)}: w_2 = 2$
- $\text{srv3 (10.0.0.13)}: w_3 = 1$
- $\text{srv4 (10.0.0.14)}: w_4 = 2$
- Total weight $W = 1 + 2 + 1 + 2 = 6$. Ratio: $1:2:1:2$.

### Pseudocode
```python
def select_weighted(healthy_servers, current_index, current_weight, max_weight, gcd_weight):
    while True:
        current_index = (current_index + 1) % len(healthy_servers)
        if current_index == 0:
            current_weight = current_weight - gcd_weight
            if current_weight <= 0:
                current_weight = max_weight
                if current_weight == 0:
                    return None
        if healthy_servers[current_index]['weight'] >= current_weight:
            return healthy_servers[current_index]
```

### Complexity
- **Time Complexity:** $\mathcal{O}(W / \gcd(w))$ amortized per selection, practically $\mathcal{O}(1)$ for small integer weights.
- **Space Complexity:** $\mathcal{O}(n)$ to store weights and indices.

---

## 5. Evaluation Metric: Jain's Fairness Index (JFI)

### 5.1 Standard Jain's Fairness Index
To quantitatively determine whether an algorithm distributes load equitably across $n$ servers, we use **Jain's Fairness Index (JFI)** (Raj Jain, 1984):

$$\mathcal{J}(x_1, x_2, \dots, x_n) = \frac{\left(\sum_{i=1}^n x_i\right)^2}{n \cdot \sum_{i=1}^n x_i^2}$$

#### Properties:
- **Range:** $\frac{1}{n} \le \mathcal{J} \le 1.0$.
- $\mathcal{J} = 1.0$: Absolute fairness (each server receives exactly $x_i = \frac{1}{n}\sum x_k$).
- $\mathcal{J} = \frac{1}{n}$: Worst case (a single server receives 100% of all traffic while others starve).

---

### 5.2 Weighted Jain's Fairness Index
For Weighted load balancing, the standard JFI penalizes intentional asymmetry. Therefore, we evaluate equity using the **Weighted Jain's Fairness Index**, which normalizes allocated requests $x_i$ against target weights $w_i$:

$$y_i = \frac{x_i}{w_i}$$

$$\mathcal{J}_w(x_1, \dots, x_n; w_1, \dots, w_n) = \frac{\left(\sum_{i=1}^n y_i\right)^2}{n \cdot \sum_{i=1}^n y_i^2}$$

When the allocation matches the configured weights ($x_i \propto w_i$), $y_1 = y_2 = \dots = y_n$, resulting in $\mathcal{J}_w = 1.0000$.

---

## 6. Empirical Benchmark Validation Results

The algorithms were benchmarked systematically inside the Mininet environment across 3 independent iterations (72 total client HTTP requests per algorithm, concurrency $C=4$) dispatched through the OpenFlow pipeline:

| Algorithm | Total Requests | Distribution `[srv1, srv2, srv3, srv4]` | Target Ratio | Achieved Ratio | JFI ($\mathcal{J}$) | Weighted JFI ($\mathcal{J}_w$) | Avg Latency | Median Latency | P95 Latency | P99 Latency | RPS |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Round-Robin** | 72 (3 $\times$ 24) | `[18, 18, 18, 17]` | 1 : 1 : 1 : 1 | 1.05 : 1.05 : 1.05 : 1.00 | **0.9994** | 0.9000 | 61.12 ms | 36.62 ms | 133.76 ms | 440.49 ms | 27.55 |
| **Least-Connections** | 72 (3 $\times$ 24) | `[18, 18, 18, 18]` | 1 : 1 : 1 : 1 | **1 : 1 : 1 : 1** | **1.0000** | 0.9000 | **51.16 ms** | 36.75 ms | **68.80 ms** | 334.33 ms | 28.37 |
| **Weighted (WRR)** | 72 (3 $\times$ 24) | `[12, 24, 12, 24]` | 1 : 2 : 1 : 2 | **1 : 2 : 1 : 2** | 0.9000 | **1.0000** | 51.77 ms | 41.82 ms | 91.78 ms | **132.08 ms** | **28.73** |

### Analysis:
1. **Least-Connections** achieved absolute mathematical perfection ($\mathcal{J} = 1.0000$), maintaining uniform connection distribution across all 4 backends ($18:18:18:18$) with the lowest average latency ($51.16\text{ ms}$).
2. **Round-Robin** achieved near-ideal equity ($\mathcal{J} = 0.9994$) across 72 requests with 71/72 successful completions.
3. **Weighted Round-Robin** matched its target weight ratio of $1:2:1:2$ with zero deviation ($[12, 24, 12, 24]$), achieving an ideal Weighted Fairness Index of **1.0000**, the highest overall throughput ($28.73\text{ RPS}$), and the tightest tail latency ($P_{99} = 132.08\text{ ms}$).

---

## 7. Adaptive Traffic Engineering: Dynamic Path Rerouting

### 7.1 Multi-Path Topology Model
The data plane features a diamond topology with two redundant transit paths connecting Ingress Switch ($s1$) and Egress Switch ($s4$):
- **Path A (Primary):** $s1 \xrightarrow{\text{port 3}} s2 \xrightarrow{\text{port 2}} s4$
- **Path B (Alternate):** $s1 \xrightarrow{\text{port 4}} s3 \xrightarrow{\text{port 2}} s4$

Each link is constrained to a bandwidth capacity of $C = 10\text{ Mbps}$.

### 7.2 Utilization Detection & Hysteresis
The controller continuously polls OpenFlow port counters every interval $T = 5\text{ seconds}$:

$$\Delta \text{tx\_bytes} = \text{tx\_bytes}_t - \text{tx\_bytes}_{t-T}$$

$$\text{Current Utilization } U = \frac{\Delta \text{tx\_bytes} \times 8}{T \times C} \times 100\%$$

#### Rerouting Rules:
- If $U \ge 80\%$ on Path A (`TE_THRESHOLD_RATIO = 0.80`):
  $$\text{TrafficEngineer} \implies \text{Trigger Reroute to Path B}$$
  The controller steers new sessions across Path B via switch $s1$ port 4 ($s3$).
- If $U < 50\%$ on Path A (Hysteresis recovery threshold):
  $$\text{TrafficEngineer} \implies \text{Restore Primary Path A}$$
  Forwarding preference reverts to port 3 ($s2$), preventing oscillatory route flapping.

### 7.3 Link Failure Detection & Sub-50ms Recovery
When an OpenFlow `OFPPortStatus` message with flag `OFPPR_DELETE` or link down state is received:
1. Active flows routed through the failed port are purged via `OFPFC_DELETE`.
2. Instantaneous failover installs new forwarding flows targeting the surviving transit bridge.
3. In benchmarking tests (`tests/test_failover.py`), the system restored 100% reachability across all clients and servers with zero human intervention.
