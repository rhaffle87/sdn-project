"""
Topology Discovery: Datapath Tracking and Multi-Path Management
Maintains active switch datapaths, link states, and multi-path graph across the diamond topology.
"""

import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from controller import config

LOG = logging.getLogger("TopologyDiscovery")

class TopologyDiscovery:
    def __init__(self):
        # Active switch datapaths: {dpid: datapath}
        self.datapaths = {}

        # Link status: {link_name: is_up}
        self.link_status = {
            "s1-s2": True,
            "s2-s4": True,
            "s1-s3": True,
            "s3-s4": True
        }

    def register_switch(self, datapath):
        """Register a connected switch datapath."""
        dpid = datapath.id
        self.datapaths[dpid] = datapath
        LOG.info("[Topo] Registered Switch DPID: 0x%016x (%d)", dpid, dpid)

    def unregister_switch(self, datapath):
        """Unregister a disconnected switch datapath."""
        dpid = datapath.id
        if dpid in self.datapaths:
            del self.datapaths[dpid]
            LOG.info("[Topo] Unregistered Switch DPID: 0x%016x (%d)", dpid, dpid)

    def update_port_status(self, dpid, port_no, is_up):
        """Update link state based on OpenFlow PortStatus event."""
        if dpid == config.DPID_S1:
            if port_no == config.S1_PORT_TO_S2:
                self.link_status["s1-s2"] = is_up
            elif port_no == config.S1_PORT_TO_S3:
                self.link_status["s1-s3"] = is_up

        elif dpid == config.DPID_S2:
            if port_no == config.S2_PORT_TO_S1:
                self.link_status["s1-s2"] = is_up
            elif port_no == config.S2_PORT_TO_S4:
                self.link_status["s2-s4"] = is_up

        elif dpid == config.DPID_S3:
            if port_no == config.S3_PORT_TO_S1:
                self.link_status["s1-s3"] = is_up
            elif port_no == config.S3_PORT_TO_S4:
                self.link_status["s3-s4"] = is_up

        elif dpid == config.DPID_S4:
            if port_no == config.S4_PORT_TO_S2:
                self.link_status["s2-s4"] = is_up
            elif port_no == config.S4_PORT_TO_S3:
                self.link_status["s3-s4"] = is_up

        LOG.warning("[Topo] Link status update: DPID %d, Port %d, Up=%s", dpid, port_no, is_up)

    def is_path_available(self, path_name):
        """Check if both hops along a path are active."""
        if path_name == "path_a":
            return self.link_status["s1-s2"] and self.link_status["s2-s4"]
        elif path_name == "path_b":
            return self.link_status["s1-s3"] and self.link_status["s3-s4"]
        return False

    def get_active_path(self, preferred_path="path_a"):
        """
        Return an active path. If preferred path is down, fall back to alternate.
        """
        if self.is_path_available(preferred_path):
            return preferred_path
        alternate = "path_b" if preferred_path == "path_a" else "path_a"
        if self.is_path_available(alternate):
            LOG.info("[Topo] Preferred %s is DOWN; failing over to %s", preferred_path, alternate)
            return alternate
        LOG.error("[Topo] No path available between s1 and s4!")
        return preferred_path
