"""
Traffic Engineer: Adaptive Multi-Path Rerouting & Congestion Avoidance
Monitors link bandwidth utilization across Path A and Path B.
Dynamically redirects incoming traffic to alternate paths when thresholds are exceeded.
Satisfies CPMK-4 (SDN Application Ecosystem & Adaptive Traffic Engineering).
"""

import logging
import os
import sys
from ryu.lib import hub
from controller import config

LOG = logging.getLogger("TrafficEngineer")

class TrafficEngineer:
    def __init__(self, app):
        self.app = app
        self.te_enabled = True
        self.last_reroute_reason = "Initial Default: Path A"
        self.te_thread = hub.spawn(self._te_loop)

    def _te_loop(self):
        """Continuous traffic engineering optimization loop."""
        hub.sleep(5)
        while True:
            hub.sleep(config.STATS_POLL_INTERVAL)
            if self.te_enabled and hasattr(self.app, 'stats'):
                self._evaluate_link_congestion()

    def _evaluate_link_congestion(self):
        """
        Evaluate link utilization from StatsMonitor and apply rerouting policy.
        """
        link_stats = self.app.stats.get_link_utilization()
        path_a_ratio = link_stats["path_a"]["ratio"]
        path_b_ratio = link_stats["path_b"]["ratio"]
        current_path = self.app.preferred_path

        # Case 1: Primary Path A congested (> threshold) and Path B is available
        if path_a_ratio >= config.TE_THRESHOLD_RATIO and path_b_ratio < path_a_ratio:
            if current_path != "path_b" and self.app.topo.is_path_available("path_b"):
                self.app.preferred_path = "path_b"
                self.last_reroute_reason = (f"Congestion on Path A ({path_a_ratio*100:.1f}% >= "
                                           f"{config.TE_THRESHOLD_RATIO*100:.1f}%). Rerouted to Path B.")
                LOG.warning("[TE] *** ADAPTIVE REROUTING TRIGGERED *** %s", self.last_reroute_reason)

        # Case 2: Path A has cooled down below 50% utilization (Hysteresis)
        elif path_a_ratio < 0.50 and current_path == "path_b":
            if self.app.topo.is_path_available("path_a"):
                self.app.preferred_path = "path_a"
                self.last_reroute_reason = (f"Path A recovered ({path_a_ratio*100:.1f}% < 50%). "
                                           f"Restored Path A preference.")
                LOG.info("[TE] *** RESTORING PRIMARY PATH *** %s", self.last_reroute_reason)

    def force_path(self, path_name):
        """Manually force traffic preference to path_a or path_b."""
        if path_name in ["path_a", "path_b"]:
            self.app.preferred_path = path_name
            self.last_reroute_reason = f"Manual override to {path_name}"
            LOG.info("[TE] Manual path override set to: %s", path_name)
            return True
        return False

    def get_te_status(self):
        """Return status dictionary for live dashboard and telemetry reporting."""
        link_stats = self.app.stats.get_link_utilization() if hasattr(self.app, 'stats') else {}
        return {
            "te_enabled": self.te_enabled,
            "preferred_path": self.app.preferred_path,
            "threshold_ratio": config.TE_THRESHOLD_RATIO,
            "link_capacity_bps": config.LINK_CAPACITY_BPS,
            "link_stats": link_stats,
            "last_reason": self.last_reroute_reason
        }
