"""
Configuration Constants for SDN Load Balancer & Traffic Engineering
Defines VIP, backend server specifications, OpenFlow priorities, and timing parameters.
"""

# Virtual Service Definition
VIP = "10.0.0.100"
VIP_MAC = "00:00:00:00:00:fe"
SERVICE_PORT = 80

# Backend Server Pool Definitions
# Maps server id to IP, MAC, attached switch port on s4, and weight
BACKEND_POOL = [
    {
        "id": "srv1",
        "ip": "10.0.0.11",
        "mac": "00:00:00:00:00:11",
        "port": 80,
        "s4_port": 1,
        "weight": 1,
        "healthy": True
    },
    {
        "id": "srv2",
        "ip": "10.0.0.12",
        "mac": "00:00:00:00:00:12",
        "port": 80,
        "s4_port": 2,
        "weight": 2,
        "healthy": True
    },
    {
        "id": "srv3",
        "ip": "10.0.0.13",
        "mac": "00:00:00:00:00:13",
        "port": 80,
        "s4_port": 3,
        "weight": 1,
        "healthy": True
    },
    {
        "id": "srv4",
        "ip": "10.0.0.14",
        "mac": "00:00:00:00:00:14",
        "port": 80,
        "s4_port": 4,
        "weight": 2,
        "healthy": True
    }
]

# Client Host Definitions (attached to s1)
CLIENT_POOL = {
    "10.0.0.1": {"mac": "00:00:00:00:00:01", "s1_port": 1},
    "10.0.0.2": {"mac": "00:00:00:00:00:02", "s1_port": 2}
}

# Switch DPID Definitions
DPID_S1 = 1  # Ingress Switch (Clients h1, h2)
DPID_S2 = 2  # Transit Core Switch (Upper Path A)
DPID_S3 = 3  # Transit Core Switch (Lower Path B)
DPID_S4 = 4  # Egress Switch (Server Farm srv1..srv4)

# Switch Inter-Connect Port Map
# s1 ports: 1: h1, 2: h2, 3: s2, 4: s3
# s2 ports: 1: s1, 2: s4
# s3 ports: 1: s1, 2: s4
# s4 ports: 1: srv1, 2: srv2, 3: srv3, 4: srv4, 5: s2, 6: s3
S1_PORT_TO_S2 = 3
S1_PORT_TO_S3 = 4
S2_PORT_TO_S1 = 1
S2_PORT_TO_S4 = 2
S3_PORT_TO_S1 = 1
S3_PORT_TO_S4 = 2
S4_PORT_TO_S2 = 5
S4_PORT_TO_S3 = 6

# OpenFlow Priority Hierarchy
PRIO_HEALTH_BYPASS = 100     # Direct health monitoring traffic (bypasses NAT)
PRIO_FORWARD_NAT = 50        # VIP -> Backend NAT rewrite (embeds TE transit output port)
PRIO_REVERSE_NAT = 40        # Backend -> VIP reverse NAT rewrite
PRIO_ARP = 30                # Proactive VIP Proxy ARP flow on s1 & reactive responder
PRIO_TRAFFIC_ENG = 20        # Traffic engineering overrides (reserved for L3 bulk transit)
PRIO_UNICAST_LEARNED = 10    # Standard L2/L3 learned unicast
PRIO_TABLE_MISS = 0          # Table-Miss default (to controller via Packet-In)

# Flow Timeout Settings (in seconds)
IDLE_TIMEOUT_NAT = 20        # Reclaim inactive TCP session flows
HARD_TIMEOUT_NAT = 60        # Upper bound lifetime for TCP session
IDLE_TIMEOUT_LEARNED = 30    # Reclaim learned MAC flows
HARD_TIMEOUT_LEARNED = 60

# Load Balancing Algorithm Modes
ALGO_ROUND_ROBIN = "round_robin"
ALGO_LEAST_CONNECTIONS = "least_connections"
ALGO_WEIGHTED = "weighted"
DEFAULT_ALGORITHM = ALGO_ROUND_ROBIN

# Traffic Engineering & Telemetry Settings
LINK_CAPACITY_BPS = 10 * 1000 * 1000  # 10 Mbps
TE_THRESHOLD_RATIO = 0.80             # 80% bandwidth triggers alternate path
STATS_POLL_INTERVAL = 5               # Port/flow stats polling interval (seconds)
HEALTH_CHECK_INTERVAL = 10            # Active health probe interval (seconds)
HEALTH_FAIL_LIMIT = 5                 # Consecutive fails before marking DOWN
