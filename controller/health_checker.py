"""
Health Checker: Active TCP/HTTP Health Prober for Backend Server Farm
Periodically verifies availability of backend servers via /health endpoint.
Automatically marks failing servers DOWN and recovers healthy servers back into the pool.
"""

import json
import logging
import os
import sys
import urllib.request
from ryu.lib import hub
from controller import config

LOG = logging.getLogger("HealthChecker")

class HealthChecker:
    def __init__(self, app):
        self.app = app
        self.fail_counts = {b["id"]: 0 for b in self.app.lb.backends}
        self.manual_overrides = {}
        self.probe_thread = hub.spawn(self._probe_loop)

    def _probe_loop(self):
        """Continuous health monitoring loop."""
        # Wait initial 5 seconds for servers and topology to boot
        hub.sleep(5)
        while True:
            self._probe_all_backends()
            hub.sleep(config.HEALTH_CHECK_INTERVAL)

    def _probe_all_backends(self):
        """Probe all configured backend servers."""
        # Only probe if Egress switch s4 is actively connected to the controller
        if config.DPID_S4 not in self.app.topo.datapaths:
            return

        for backend in self.app.lb.backends:
            b_id = backend["id"]
            ip = backend["ip"]
            port = backend["port"]
            url = f"http://{ip}:{port}/health"

            # If operator manually disabled this server, honor the override
            if self.manual_overrides.get(b_id) is False:
                continue

            is_alive = False
            route_error = False
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SDN-HealthChecker/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status == 200:
                        body = json.loads(resp.read().decode())
                        if body.get("status") == "UP":
                            is_alive = True
            except OSError as oe:
                if getattr(oe, 'errno', None) in (101, 113):  # Network unreachable or No route to host
                    route_error = True
            except urllib.error.URLError as ue:
                if hasattr(ue, 'reason') and isinstance(ue.reason, OSError):
                    if getattr(ue.reason, 'errno', None) in (101, 113):
                        route_error = True
            except Exception:
                is_alive = False

            if route_error:
                # Do not mark servers DOWN if host namespace has no route to Mininet
                continue

            if is_alive:
                if self.fail_counts[b_id] > 0:
                    LOG.info("[Health] Backend %s responded OK (was failing %d times)", b_id, self.fail_counts[b_id])
                self.fail_counts[b_id] = 0
                if not backend.get("healthy", True):
                    LOG.info("[Health] RECOVERY: Backend %s is back ONLINE!", b_id)
                    self.app.lb.update_health_status(b_id, True)
            else:
                self.fail_counts[b_id] += 1
                LOG.warning("[Health] Probe failed for backend %s (%d/%d)",
                            b_id, self.fail_counts[b_id], config.HEALTH_FAIL_LIMIT)
                if self.fail_counts[b_id] >= config.HEALTH_FAIL_LIMIT:
                    if backend.get("healthy", True):
                        LOG.error("[Health] OUTAGE DETECTED: Marking backend %s DOWN!", b_id)
                        self.app.lb.update_health_status(b_id, False)

    def force_set_health(self, backend_id, is_healthy):
        """Manually override health state of a backend."""
        self.manual_overrides[backend_id] = bool(is_healthy)
        self.app.lb.update_health_status(backend_id, is_healthy)
        self.fail_counts[backend_id] = 0 if is_healthy else config.HEALTH_FAIL_LIMIT
        # Optionally notify backend server /health/toggle
        for b in self.app.lb.backends:
            if b["id"] == backend_id:
                try:
                    url = f"http://{b['ip']}:{b['port']}/health/toggle"
                    req = urllib.request.Request(url, data=b"", headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(req, timeout=1.0) as _:
                        pass
                except Exception:
                    pass
                break
        return True
