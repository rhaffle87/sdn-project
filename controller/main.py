"""
Main Ryu SDN Controller Application: Load Balancer & Traffic Engineering Orchestrator
OpenFlow 1.3 Reactive Pipeline with Bidirectional NAT Rewriting, ARP Handling, and Multi-Path Dispatch.
"""

import json
import os
import sys

# Ensure project root is in sys.path when launched via ryu-manager
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, tcp, icmp
from ryu.app.wsgi import WSGIApplication, ControllerBase, Response, route

from controller import config
from controller.flow_manager import add_flow, send_packet_out
from controller.load_balancer import LoadBalancer
from controller.topology_discovery import TopologyDiscovery
from controller.stats_monitor import StatsMonitor
from controller.health_checker import HealthChecker
from controller.traffic_engineer import TrafficEngineer

# REST API URL Prefix
REST_URL_PREFIX = '/api'
REST_INSTANCE_NAME = 'loadbalancer_api_app'

class SDNLoadBalancerApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(SDNLoadBalancerApp, self).__init__(*args, **kwargs)
        self.name = 'sdn_load_balancer'
        self.topo = TopologyDiscovery()
        self.lb = LoadBalancer()

        # MAC-to-port learning table: {dpid: {mac: port}}
        # Seed with static host-facing ports to prevent broadcast loops across diamond topology
        self.mac_to_port = {
            config.DPID_S1: {c["mac"]: c["s1_port"] for c in config.CLIENT_POOL.values()},
            config.DPID_S4: {b["mac"]: b["s4_port"] for b in config.BACKEND_POOL}
        }

        # Preferred transit path (can be changed by TrafficEngineer)
        self.preferred_path = "path_a"

        # Initialize Telemetry, Active Health Probing, and Traffic Engineering
        self.stats = StatsMonitor(self)
        self.health = HealthChecker(self)
        self.te = TrafficEngineer(self)

        # Register WSGI REST endpoints
        wsgi = kwargs['wsgi']
        wsgi.register(LoadBalancerRestController, {REST_INSTANCE_NAME: self})
        self.logger.info("=== [SDN Controller] Initialized OpenFlow 1.3 Load Balancer App ===")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Switch handshake: Install Table-Miss flow entry (Priority 0).
        Sends all unhandled packets to the controller via Packet-In.
        """
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # 1. Install Default Table-Miss entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        add_flow(datapath, config.PRIO_TABLE_MISS, match, actions, idle_timeout=0, hard_timeout=0)

        # 2. Register with topology tracker
        self.topo.register_switch(datapath)
        self.mac_to_port.setdefault(datapath.id, {})
        self.logger.info("[OFP] Switch connected and Table-Miss installed: DPID 0x%016x", datapath.id)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        """Handle link up/down state changes."""
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        port_no = msg.desc.port_no
        link_down = (msg.desc.state & ofp.OFPPS_LINK_DOWN) or (msg.desc.config & ofp.OFPPC_PORT_DOWN)
        is_up = not bool(link_down)

        self.topo.update_port_status(dp.id, port_no, is_up)
        self.logger.info("[OFP] PortStatus: DPID %d Port %d is %s", dp.id, port_no, "UP" if is_up else "DOWN")

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Delegate port stats message to StatsMonitor."""
        self.stats.handle_port_stats_reply(ev)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """Delegate flow stats message to StatsMonitor for per-backend flow counting."""
        self.stats.handle_flow_stats_reply(ev)

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        """Track connection closure when NAT flows expire."""
        msg = ev.msg
        match = msg.match
        if 'ipv4_dst' in match:
            dst = match['ipv4_dst']
            for b in self.lb.backends:
                if b['ip'] == dst:
                    self.lb.connection_closed(b['id'])
                    break

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Main packet processing pipeline:
        1. Intercept ARP targeting VIP -> Send ARP reply with VIP_MAC.
        2. Intercept TCP targeting VIP -> Perform LB selection & install bidirectional NAT.
        3. Fallback: Reactive L2 learning switch.
        """
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        if not eth_pkt:
            return

        eth_src = eth_pkt.src
        eth_dst = eth_pkt.dst
        eth_type = eth_pkt.ethertype

        # Ignore LLDP
        if eth_type == ether_types.ETH_TYPE_LLDP:
            return

        # -------------------------------------------------------------
        # 1. ARP Resolution Pipeline
        # -------------------------------------------------------------
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt:
            # Check if this ARP is targeted at the VIP
            if self.lb.handle_arp(datapath, in_port, arp_pkt):
                return
            # Standard ARP learning and flooding
            self._handle_l2_forwarding(datapath, in_port, eth_src, eth_dst, msg, pkt, is_arp=True)
            return

        # -------------------------------------------------------------
        # 2. IPv4 / TCP Load Balancing Pipeline
        # -------------------------------------------------------------
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            # Check for traffic targeting the Virtual IP
            if ip_pkt.dst == config.VIP:
                tcp_pkt = pkt.get_protocol(tcp.tcp)
                if tcp_pkt and tcp_pkt.dst_port == config.SERVICE_PORT:
                    client_ip = ip_pkt.src
                    client_port = tcp_pkt.src_port

                    # Select backend according to active LB algorithm
                    backend = self.lb.select_backend(client_ip, client_port)

                    # Determine active path (Path A or Path B)
                    active_path = self.topo.get_active_path(self.preferred_path)

                    # Install symmetrical forward and reverse NAT rules
                    success = self.lb.install_nat_flows(
                        datapaths=self.topo.datapaths,
                        client_ip=client_ip,
                        client_mac=eth_src,
                        client_port=client_port,
                        client_in_port=in_port,
                        backend=backend,
                        path_choice=active_path
                    )

                    # Forward the initial packet directly to avoid dropping the SYN
                    if success:
                        out_port = config.S1_PORT_TO_S2 if active_path == "path_a" else config.S1_PORT_TO_S3
                        actions = [
                            parser.OFPActionSetField(ipv4_dst=backend["ip"]),
                            parser.OFPActionSetField(eth_dst=backend["mac"]),
                            parser.OFPActionOutput(out_port)
                        ]
                        send_packet_out(datapath, msg.buffer_id, in_port, actions, msg.data)
                        return

        # -------------------------------------------------------------
        # 3. Standard L2 Learning Switch Pipeline (Host-to-Host / ICMP)
        # -------------------------------------------------------------
        self._handle_l2_forwarding(datapath, in_port, eth_src, eth_dst, msg, pkt)

    def _handle_l2_forwarding(self, datapath, in_port, eth_src, eth_dst, msg, pkt, is_arp=False):
        """Standard L2 MAC learning and unicast forwarding."""
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][eth_src] = in_port

        if eth_dst in self.mac_to_port.get(dpid, {}):
            out_port = self.mac_to_port[dpid][eth_dst]
        else:
            # Do not flood inter-switch mesh to prevent broadcast storms
            return

        actions = [parser.OFPActionOutput(out_port)]

        # Install flow rule if unicast
        if out_port != ofproto.OFPP_FLOOD and not is_arp:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth_dst, eth_src=eth_src)
            add_flow(datapath, config.PRIO_UNICAST_LEARNED, match, actions,
                     idle_timeout=config.IDLE_TIMEOUT_LEARNED, hard_timeout=config.HARD_TIMEOUT_LEARNED)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        send_packet_out(datapath, msg.buffer_id, in_port, actions, data=data)


class LoadBalancerRestController(ControllerBase):
    """Ryu WSGI REST Controller exposing Load Balancer and Telemetry state."""

    def __init__(self, req, link, data, **config_dict):
        super(LoadBalancerRestController, self).__init__(req, link, data, **config_dict)
        self.app = data[REST_INSTANCE_NAME]

    @route('loadbalancer', '/api/stats', methods=['GET'])
    def get_stats(self, req, **_kwargs):
        """GET /api/stats: Return request counters, active connections, and algorithm."""
        body = json.dumps({
            "algorithm": self.app.lb.algorithm,
            "preferred_path": self.app.preferred_path,
            "total_requests": self.app.lb.total_requests,
            "active_connections": self.app.lb.active_connections,
            "backends": self.app.lb.backends,
            "link_status": self.app.topo.link_status
        }, indent=2)
        return Response(content_type='application/json', body=body)

    @route('loadbalancer', '/api/algorithm', methods=['POST'])
    def set_algorithm(self, req, **_kwargs):
        """POST /api/algorithm: Set active algorithm (round_robin, least_connections, weighted)."""
        try:
            data = json.loads(req.body.decode('utf-8'))
            algo = data.get('algorithm')
            if algo and self.app.lb.set_algorithm(algo):
                return Response(status=200, content_type='application/json',
                                body=json.dumps({"status": "success", "algorithm": algo}))
            return Response(status=400, content_type='application/json',
                            body=json.dumps({"status": "error", "message": "Invalid algorithm name"}))
        except Exception as e:
            return Response(status=500, content_type='application/json',
                            body=json.dumps({"status": "error", "message": str(e)}))

    @route('loadbalancer', '/api/telemetry', methods=['GET'])
    def get_telemetry(self, req, **_kwargs):
        """GET /api/telemetry: Return real-time link bandwidth utilization and TE status."""
        body = json.dumps({
            "traffic_engineering": self.app.te.get_te_status(),
            "link_utilization": self.app.stats.get_link_utilization(),
            "flow_counts": self.app.stats.get_flow_counts(),
            "active_connections": self.app.lb.active_connections,
            "total_requests": self.app.lb.total_requests
        }, indent=2)
        return Response(content_type='application/json', body=body)

    @route('loadbalancer', '/api/traffic-engineer/path', methods=['POST'])
    def set_path(self, req, **_kwargs):
        """POST /api/traffic-engineer/path: Manually override preferred path (path_a or path_b)."""
        try:
            data = json.loads(req.body.decode('utf-8'))
            path = data.get('path')
            if path and self.app.te.force_path(path):
                return Response(status=200, content_type='application/json',
                                body=json.dumps({"status": "success", "preferred_path": path}))
            return Response(status=400, content_type='application/json',
                            body=json.dumps({"status": "error", "message": "Invalid path name (use 'path_a' or 'path_b')"}))
        except Exception as e:
            return Response(status=500, content_type='application/json',
                            body=json.dumps({"status": "error", "message": str(e)}))

    @route('loadbalancer', '/api/backend/health', methods=['POST'])
    def set_backend_health(self, req, **_kwargs):
        """POST /api/backend/health: Manually override health state of a backend."""
        try:
            data = json.loads(req.body.decode('utf-8'))
            backend_id = data.get('backend_id')
            is_healthy = data.get('healthy')
            if backend_id is not None and is_healthy is not None:
                self.app.health.force_set_health(backend_id, bool(is_healthy))
                return Response(status=200, content_type='application/json',
                                body=json.dumps({"status": "success", "backend_id": backend_id, "healthy": is_healthy}))
            return Response(status=400, content_type='application/json',
                            body=json.dumps({"status": "error", "message": "Missing backend_id or healthy field"}))
        except Exception as e:
            return Response(status=500, content_type='application/json',
                            body=json.dumps({"status": "error", "message": str(e)}))
