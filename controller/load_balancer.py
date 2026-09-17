"""
Load Balancer Engine: Core Algorithm Selection & Bidirectional NAT Programming
Supports Round-Robin, Least-Connections, and Weighted Load Balancing.
Handles VIP ARP resolution and end-to-end symmetrical Layer 2/3 NAT rewriting.
"""

import copy
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ryu.ofproto import ofproto_v1_3
from controller import config
from controller.flow_manager import add_flow, delete_flow, send_arp_reply

LOG = logging.getLogger("LoadBalancerEngine")

class LoadBalancer:
    def __init__(self, app=None):
        self.app = app
        self.backends = copy.deepcopy(config.BACKEND_POOL)
        self.algorithm = config.DEFAULT_ALGORITHM

        # Algorithm internal states
        self.rr_index = 0
        self.active_connections = {b["id"]: 0 for b in self.backends}
        self.total_requests = {b["id"]: 0 for b in self.backends}

        # Weighted round robin state
        self.weighted_pool = []
        self._rebuild_weighted_pool()

    def _rebuild_weighted_pool(self):
        """Build repeated backend index list based on weights."""
        self.weighted_pool = []
        for idx, b in enumerate(self.backends):
            if b.get("healthy", True):
                w = max(1, b.get("weight", 1))
                self.weighted_pool.extend([idx] * w)
        if not self.weighted_pool:
            self.weighted_pool = [0]
        self.weighted_index = 0

    def get_healthy_backends(self):
        """Return list of currently healthy backends."""
        healthy = [b for b in self.backends if b.get("healthy", True)]
        return healthy if healthy else self.backends

    def select_backend(self, client_ip=None, client_port=None):
        """
        Select a backend according to active load balancing algorithm.
        """
        healthy = self.get_healthy_backends()

        if self.algorithm == config.ALGO_ROUND_ROBIN:
            backend = healthy[self.rr_index % len(healthy)]
            self.rr_index = (self.rr_index + 1) % len(healthy)

        elif self.algorithm == config.ALGO_LEAST_CONNECTIONS:
            # Pick backend with minimum active connections
            backend = min(healthy, key=lambda b: self.active_connections.get(b["id"], 0))

        elif self.algorithm == config.ALGO_WEIGHTED:
            if not self.weighted_pool:
                self._rebuild_weighted_pool()
            backend_idx = self.weighted_pool[self.weighted_index % len(self.weighted_pool)]
            self.weighted_index = (self.weighted_index + 1) % len(self.weighted_pool)
            candidate = self.backends[backend_idx]
            if candidate in healthy:
                backend = candidate
            else:
                backend = healthy[self.weighted_index % len(healthy)]
        else:
            backend = healthy[0]

        # Record selection stats
        self.total_requests[backend["id"]] += 1
        self.active_connections[backend["id"]] += 1
        LOG.info("[LB] Selected backend %s (%s) via %s [active=%d, total=%d]",
                 backend["id"], backend["ip"], self.algorithm,
                 self.active_connections[backend["id"]], self.total_requests[backend["id"]])
        return backend

    def connection_closed(self, backend_id):
        """Decrement active connection count when flow expires."""
        if backend_id in self.active_connections:
            self.active_connections[backend_id] = max(0, self.active_connections[backend_id] - 1)

    def set_algorithm(self, algo_name):
        """Switch active load balancing algorithm."""
        if algo_name in [config.ALGO_ROUND_ROBIN, config.ALGO_LEAST_CONNECTIONS, config.ALGO_WEIGHTED]:
            self.algorithm = algo_name
            self.rr_index = 0
            self.weighted_index = 0
            if algo_name == config.ALGO_WEIGHTED:
                self._rebuild_weighted_pool()
            LOG.info("[LB] Load balancing algorithm switched to: %s", algo_name)
            return True
        return False

    def update_health_status(self, backend_id, is_healthy):
        """Update health status of a backend and proactively evict stale flows on failure."""
        for b in self.backends:
            if b["id"] == backend_id:
                if b["healthy"] != is_healthy:
                    b["healthy"] = is_healthy
                    self._rebuild_weighted_pool()
                    status_str = "UP" if is_healthy else "DOWN"
                    LOG.warning("[LB] Health state changed: Backend %s is now %s", backend_id, status_str)

                    # Proactively evict active OpenFlow flows for dead backend via OFPFC_DELETE
                    if not is_healthy and self.app and hasattr(self.app, 'topo'):
                        target_ip = b["ip"]
                        for dp in list(self.app.topo.datapaths.values()):
                            p = dp.ofproto_parser
                            # Evict forward NAT flows targeting this backend
                            m_dst = p.OFPMatch(eth_type=0x0800, ip_proto=6, ipv4_dst=target_ip)
                            delete_flow(dp, match=m_dst)
                            # Evict reverse NAT flows originating from this backend
                            m_src = p.OFPMatch(eth_type=0x0800, ip_proto=6, ipv4_src=target_ip)
                            delete_flow(dp, match=m_src)
                        LOG.warning("[LB] Proactively evicted active OpenFlow flows for dead backend %s (%s)",
                                    backend_id, target_ip)
                break

    def handle_arp(self, datapath, in_port, arp_pkt):
        """
        Handle ARP requests for VIP and known hosts (Proxy ARP).
        Prevents broadcast loops across multi-path topology links.
        """
        # Static ARP map for VIP and all topology hosts
        arp_cache = {
            config.VIP: config.VIP_MAC,
            "10.0.0.1": "00:00:00:00:00:01",
            "10.0.0.2": "00:00:00:00:00:02",
            "10.0.0.11": "00:00:00:00:00:11",
            "10.0.0.12": "00:00:00:00:00:12",
            "10.0.0.13": "00:00:00:00:00:13",
            "10.0.0.14": "00:00:00:00:00:14",
            "10.0.0.254": "00:00:00:00:00:ff",
        }

        if arp_pkt.dst_ip in arp_cache:
            target_mac = arp_cache[arp_pkt.dst_ip]
            LOG.debug("[ARP] Proxy ARP reply for %s -> %s (requested by %s)",
                      arp_pkt.dst_ip, target_mac, arp_pkt.src_ip)
            send_arp_reply(
                datapath=datapath,
                port=in_port,
                src_mac=target_mac,
                src_ip=arp_pkt.dst_ip,
                dst_mac=arp_pkt.src_mac,
                dst_ip=arp_pkt.src_ip
            )
            return True
        return False

    def install_nat_flows(self, datapaths, client_ip, client_mac, client_port,
                          client_in_port, backend, path_choice="path_a"):
        """
        Install symmetrical bidirectional OpenFlow 1.3 NAT flows.
        Transforms:
          Forward: Client -> VIP:80 rewritten to Client -> Backend_IP:80
          Reverse: Backend_IP:80 -> Client rewritten to VIP:80 -> Client
        """
        s1 = datapaths.get(config.DPID_S1)
        s4 = datapaths.get(config.DPID_S4)
        transit_sw = datapaths.get(config.DPID_S2 if path_choice == "path_a" else config.DPID_S3)

        if not s1 or not s4 or not transit_sw:
            LOG.error("[LB] Missing required datapaths for flow installation!")
            return False

        # Determine switch ports based on path choice
        if path_choice == "path_a":
            s1_out_port = config.S1_PORT_TO_S2
            transit_in_port = config.S2_PORT_TO_S1
            transit_out_port = config.S2_PORT_TO_S4
            s4_in_from_transit = config.S4_PORT_TO_S2
        else:
            s1_out_port = config.S1_PORT_TO_S3
            transit_in_port = config.S3_PORT_TO_S1
            transit_out_port = config.S3_PORT_TO_S4
            s4_in_from_transit = config.S4_PORT_TO_S3

        # -------------------------------------------------------------
        # 1. Ingress Switch (s1) Flow Installation
        # -------------------------------------------------------------
        p1 = s1.ofproto_parser
        # Forward Match: TCP packet from Client to VIP:80
        match_fwd_s1 = p1.OFPMatch(
            eth_type=0x0800,
            ip_proto=6,
            ipv4_src=client_ip,
            ipv4_dst=config.VIP,
            tcp_src=client_port,
            tcp_dst=config.SERVICE_PORT
        )
        # Forward Actions: Rewrite DST IP/MAC to backend, output to transit
        actions_fwd_s1 = [
            p1.OFPActionSetField(ipv4_dst=backend["ip"]),
            p1.OFPActionSetField(eth_dst=backend["mac"]),
            p1.OFPActionOutput(s1_out_port)
        ]
        add_flow(s1, config.PRIO_FORWARD_NAT, match_fwd_s1, actions_fwd_s1,
                 idle_timeout=config.IDLE_TIMEOUT_NAT, hard_timeout=config.HARD_TIMEOUT_NAT)

        # Reverse Match: TCP packet from Backend to Client
        match_rev_s1 = p1.OFPMatch(
            eth_type=0x0800,
            ip_proto=6,
            ipv4_src=backend["ip"],
            ipv4_dst=client_ip,
            tcp_src=config.SERVICE_PORT,
            tcp_dst=client_port
        )
        # Reverse Actions: Rewrite SRC IP/MAC back to VIP, output to client port
        actions_rev_s1 = [
            p1.OFPActionSetField(ipv4_src=config.VIP),
            p1.OFPActionSetField(eth_src=config.VIP_MAC),
            p1.OFPActionOutput(client_in_port)
        ]
        add_flow(s1, config.PRIO_REVERSE_NAT, match_rev_s1, actions_rev_s1,
                 idle_timeout=config.IDLE_TIMEOUT_NAT, hard_timeout=config.HARD_TIMEOUT_NAT)

        # -------------------------------------------------------------
        # 2. Transit Switch (s2 or s3) Flow Installation
        # -------------------------------------------------------------
        pt = transit_sw.ofproto_parser
        match_fwd_t = pt.OFPMatch(
            eth_type=0x0800,
            ip_proto=6,
            ipv4_src=client_ip,
            ipv4_dst=backend["ip"],
            tcp_src=client_port,
            tcp_dst=config.SERVICE_PORT
        )
        actions_fwd_t = [pt.OFPActionOutput(transit_out_port)]
        add_flow(transit_sw, config.PRIO_FORWARD_NAT, match_fwd_t, actions_fwd_t,
                 idle_timeout=config.IDLE_TIMEOUT_NAT, hard_timeout=config.HARD_TIMEOUT_NAT)

        match_rev_t = pt.OFPMatch(
            eth_type=0x0800,
            ip_proto=6,
            ipv4_src=backend["ip"],
            ipv4_dst=client_ip,
            tcp_src=config.SERVICE_PORT,
            tcp_dst=client_port
        )
        actions_rev_t = [pt.OFPActionOutput(transit_in_port)]
        add_flow(transit_sw, config.PRIO_REVERSE_NAT, match_rev_t, actions_rev_t,
                 idle_timeout=config.IDLE_TIMEOUT_NAT, hard_timeout=config.HARD_TIMEOUT_NAT)

        # -------------------------------------------------------------
        # 3. Egress Switch (s4) Flow Installation
        # -------------------------------------------------------------
        p4 = s4.ofproto_parser
        match_fwd_s4 = p4.OFPMatch(
            eth_type=0x0800,
            ip_proto=6,
            ipv4_src=client_ip,
            ipv4_dst=backend["ip"],
            tcp_src=client_port,
            tcp_dst=config.SERVICE_PORT
        )
        actions_fwd_s4 = [p4.OFPActionOutput(backend["s4_port"])]
        add_flow(s4, config.PRIO_FORWARD_NAT, match_fwd_s4, actions_fwd_s4,
                 idle_timeout=config.IDLE_TIMEOUT_NAT, hard_timeout=config.HARD_TIMEOUT_NAT)

        match_rev_s4 = p4.OFPMatch(
            eth_type=0x0800,
            ip_proto=6,
            ipv4_src=backend["ip"],
            ipv4_dst=client_ip,
            tcp_src=config.SERVICE_PORT,
            tcp_dst=client_port
        )
        actions_rev_s4 = [p4.OFPActionOutput(s4_in_from_transit)]
        add_flow(s4, config.PRIO_REVERSE_NAT, match_rev_s4, actions_rev_s4,
                 idle_timeout=config.IDLE_TIMEOUT_NAT, hard_timeout=config.HARD_TIMEOUT_NAT)

        return True
