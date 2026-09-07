"""
Stats Monitor: OpenFlow 1.3 Port & Flow Statistics Collector
Periodically polls switches via OFPPortStatsRequest and OFPFlowStatsRequest.
Computes real-time bandwidth utilization, throughput, and active connection counts.
"""

import logging
import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3
from controller import config

LOG = logging.getLogger("StatsMonitor")

class StatsMonitor:
    def __init__(self, app):
        self.app = app
        self.datapaths = app.topo.datapaths

        # Previous port stats: {(dpid, port_no): (bytes, timestamp)}
        self.prev_port_stats = {}

        # Current link utilization in bits per second and ratio:
        # {"path_a": {"bps": 0, "ratio": 0.0}, "path_b": {"bps": 0, "ratio": 0.0}}
        self.link_stats = {
            "path_a": {"bps": 0.0, "ratio": 0.0, "tx_bytes": 0},
            "path_b": {"bps": 0.0, "ratio": 0.0, "tx_bytes": 0}
        }

        # Port to link name mapping on s1 (Ingress Switch)
        self.s1_port_to_path = {
            config.S1_PORT_TO_S2: "path_a",
            config.S1_PORT_TO_S3: "path_b"
        }

        # Spawn periodic polling green thread
        self.monitor_thread = hub.spawn(self._monitor_loop)

    def _monitor_loop(self):
        """Periodic background polling loop."""
        while True:
            hub.sleep(config.STATS_POLL_INTERVAL)
            for dp in list(self.datapaths.values()):
                self._send_port_stats_request(dp)

    def _send_port_stats_request(self, datapath):
        """Send OFPPortStatsRequest to datapath."""
        ofp = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofp.OFPP_ANY)
        datapath.send_msg(req)

    def handle_port_stats_reply(self, ev):
        """
        Process OFPPortStatsReply message from switch.
        Calculates delta bytes and bandwidth utilization rate.
        """
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        now = time.time()

        for stat in msg.body:
            port_no = stat.port_no
            # Ignore local switch port
            if port_no > ofproto_v1_3.OFPP_MAX:
                continue

            key = (dpid, port_no)
            tx_bytes = stat.tx_bytes

            if key in self.prev_port_stats:
                prev_bytes, prev_time = self.prev_port_stats[key]
                delta_t = now - prev_time
                if delta_t > 0:
                    delta_bytes = tx_bytes - prev_bytes
                    rate_bps = (delta_bytes * 8) / delta_t
                    ratio = min(1.0, rate_bps / config.LINK_CAPACITY_BPS)

                    # If this is s1 ports connected to transit links, record path utilization
                    if dpid == config.DPID_S1 and port_no in self.s1_port_to_path:
                        path_name = self.s1_port_to_path[port_no]
                        self.link_stats[path_name]["bps"] = round(rate_bps, 2)
                        self.link_stats[path_name]["ratio"] = round(ratio, 4)
                        self.link_stats[path_name]["tx_bytes"] = tx_bytes
                        LOG.debug("[Stats] Link %s (Port %d): %.2f kbps (%.1f%%)",
                                  path_name, port_no, rate_bps / 1000.0, ratio * 100.0)

            self.prev_port_stats[key] = (tx_bytes, now)

    def get_link_utilization(self):
        """Return snapshot of link utilization statistics."""
        return self.link_stats
