#!/usr/bin/env python3
"""
SDN Load Balancer & Adaptive Traffic Engineering Dashboard
Enterprise NOC-grade live telemetry console.
Dual-mode: proxies live Ryu/Mininet or runs autonomous simulation.
"""

import collections
import copy
import json
import logging
import os
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

RYU_REST_BASE = "http://127.0.0.1:8080/api"

# ---------------------------------------------------------------------------
# Autonomous Simulation State
# ---------------------------------------------------------------------------
_sim_lock = threading.Lock()
_sim = {
    "algorithm": "round_robin",
    "rr_index": 0,
    "preferred_path": "path_a",
    "manual_override": False,
    "backends": [
        {"id": "srv1", "ip": "10.0.0.11", "mac": "00:00:00:00:00:11", "port": 80, "weight": 1, "healthy": True},
        {"id": "srv2", "ip": "10.0.0.12", "mac": "00:00:00:00:00:12", "port": 80, "weight": 2, "healthy": True},
        {"id": "srv3", "ip": "10.0.0.13", "mac": "00:00:00:00:00:13", "port": 80, "weight": 1, "healthy": True},
        {"id": "srv4", "ip": "10.0.0.14", "mac": "00:00:00:00:00:14", "port": 80, "weight": 2, "healthy": True},
    ],
    "total_requests": {"srv1": 0, "srv2": 0, "srv3": 0, "srv4": 0},
    "active_connections": {"srv1": 0, "srv2": 0, "srv3": 0, "srv4": 0},
    "path_a_bytes": 0,
    "path_b_bytes": 0,
    "path_a_tx_total": 0,
    "path_b_tx_total": 0,
    "last_ts": time.time(),
    "path_a_bps": 0.0,
    "path_b_bps": 0.0,
    "te_congested": False,
    "te_hold_cycles": 0,
    "total_dispatched": 0,
    "latencies": [],
    "link_capacity_bps": 10_000_000,
    "events": [],
}
_weighted_pool_cache: list = []


def _rebuild_pool():
    global _weighted_pool_cache
    pool = []
    for b in _sim["backends"]:
        if b["healthy"]:
            pool.extend([b["id"]] * b["weight"])
    _weighted_pool_cache = pool


_rebuild_pool()


def _sim_select_backend(algo):
    healthy = [b for b in _sim["backends"] if b["healthy"]]
    if not healthy:
        return None
    if algo == "round_robin":
        idx = _sim["rr_index"] % len(healthy)
        _sim["rr_index"] = (idx + 1) % len(healthy)
        return healthy[idx]["id"]
    elif algo == "least_connections":
        return min(healthy, key=lambda b: _sim["active_connections"][b["id"]])["id"]
    elif algo == "weighted":
        pool = [b_id for b_id in _weighted_pool_cache
                if any(b["id"] == b_id and b["healthy"] for b in _sim["backends"])]
        if not pool:
            return healthy[0]["id"]
        return pool[_sim["rr_index"] % len(pool)]
    return healthy[0]["id"]


def _sim_dispatch(count: int) -> list:
    results = []
    with _sim_lock:
        now = time.time()
        dt = max(now - _sim["last_ts"], 0.05)
        algo = _sim["algorithm"]
        for _ in range(count):
            srv_id = _sim_select_backend(algo)
            if srv_id is None:
                results.append("error")
                continue
            latency_ms = max(8.0, round(random.gauss(42, 18), 2))
            _sim["total_requests"][srv_id] += 1
            _sim["active_connections"][srv_id] = max(0, _sim["active_connections"][srv_id] + 1)
            _sim["latencies"].append(latency_ms)
            if len(_sim["latencies"]) > 200:
                _sim["latencies"] = _sim["latencies"][-200:]
            _sim["total_dispatched"] += 1
            bytes_per_req = random.randint(1200, 4800)
            if _sim["preferred_path"] == "path_a":
                _sim["path_a_bytes"] += bytes_per_req
                _sim["path_a_tx_total"] += bytes_per_req
            else:
                _sim["path_b_bytes"] += bytes_per_req
                _sim["path_b_tx_total"] += bytes_per_req
            results.append(srv_id)
        # Audit J: Drain completed in-flight HTTP connections (~40ms latency) realistically
        for b in _sim["backends"]:
            bid = b["id"]
            if _sim["active_connections"][bid] > 0:
                drain = max(1, int(_sim["active_connections"][bid] * 0.7) + random.randint(1, 3))
                _sim["active_connections"][bid] = max(0, _sim["active_connections"][bid] - drain)
        cap = _sim["link_capacity_bps"]
        _sim["path_a_bps"] = min(int((_sim["path_a_bytes"] * 8) / dt), cap)
        _sim["path_b_bps"] = min(int((_sim["path_b_bytes"] * 8) / dt), cap)
        _sim["path_a_bytes"] = max(0, _sim["path_a_bytes"] - int(_sim["path_a_bytes"] * 0.5))
        _sim["path_b_bytes"] = max(0, _sim["path_b_bytes"] - int(_sim["path_b_bytes"] * 0.5))
        pa_ratio = _sim["path_a_bps"] / cap
        # Audit A: Proper TE rerouting hysteresis with hold-down cycles
        if not _sim["manual_override"]:
            if pa_ratio >= 0.80 and _sim["preferred_path"] == "path_a":
                _sim["preferred_path"] = "path_b"
                _sim["te_congested"] = True
                _sim["te_hold_cycles"] = 4
            elif _sim["te_congested"]:
                if _sim.get("te_hold_cycles", 0) > 0:
                    _sim["te_hold_cycles"] -= 1
                else:
                    _sim["preferred_path"] = "path_a"
                    _sim["te_congested"] = False
        _sim["last_ts"] = now
    return results


def _ryu_available() -> bool:
    try:
        urllib.request.urlopen(f"{RYU_REST_BASE}/stats", timeout=1)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Dashboard HTML (loaded from template at build time)
# ---------------------------------------------------------------------------
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SDN Network Operations Console</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2338bdf8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolygon points='12 2 2 7 12 12 22 7 12 2'/%3E%3Cpolyline points='2 17 12 22 22 17'/%3E%3Cpolyline points='2 12 12 17 22 12'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #090d16;
  --bg-mid: #0d1320;
  --surface: #111827;
  --surface-2: #1a2235;
  --border: rgba(148,163,184,0.10);
  --border-hi: rgba(148,163,184,0.20);
  --text: #94a3b8;
  --text-hi: #e2e8f0;
  --text-dim: #475569;
  --cyan: #38bdf8;
  --cyan-d: #0284c7;
  --indigo: #818cf8;
  --indigo-d: #4f46e5;
  --emerald: #10b981;
  --emerald-d: #059669;
  --amber: #f59e0b;
  --amber-d: #d97706;
  --rose: #f43f5e;
  --rose-d: #e11d48;
  --mono: 'JetBrains Mono', monospace;
  --sans: 'Inter', -apple-system, sans-serif;
  --radius: 10px;
  --shadow: 0 4px 24px rgba(0,0,0,0.45);
  --glow-cyan: 0 0 16px rgba(56,189,248,0.30);
  --glow-indigo: 0 0 16px rgba(129,140,248,0.30);
  --glow-emerald: 0 0 12px rgba(16,185,129,0.35);
  --glow-rose: 0 0 12px rgba(244,63,94,0.35);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--sans);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.5;
  overflow-x: hidden;
}
body::before {
  content: '';
  position: fixed; inset: 0;
  background-image:
    linear-gradient(rgba(56,189,248,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(56,189,248,0.025) 1px, transparent 1px);
  background-size: 48px 48px;
  pointer-events: none; z-index: 0;
}
.shell { position: relative; z-index: 1; max-width: 1440px; margin: 0 auto; padding: 0 24px 36px; }

/* Finding 11: Reduced margin to prevent dead zone */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 0 14px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 16px;
}
.topbar-left { display: flex; align-items: center; gap: 14px; min-width: 0; }
.topbar-logo {
  width: 36px; height: 36px;
  background: linear-gradient(135deg, var(--cyan-d), var(--indigo-d));
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--glow-cyan);
  flex-shrink: 0;
}
.topbar-logo svg { width: 20px; height: 20px; stroke: #fff; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.topbar-title { font-size: 1.05rem; font-weight: 600; color: var(--text-hi); letter-spacing: -0.01em; }
.topbar-sub { font-size: 0.78rem; color: var(--text-dim); font-family: var(--mono); margin-top: 1px; }
.topbar-right { display: flex; align-items: center; gap: 10px; }

/* Pass 3 Fix 9: Mobile topbar wrapping to eliminate horizontal overflow */
@media (max-width: 640px) {
  .topbar { flex-direction: column; align-items: flex-start; gap: 12px; }
  .topbar-right { flex-wrap: wrap; width: 100%; gap: 6px; }
  .topbar-sub { font-size: 0.70rem; }
}

.pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 100px;
  font-size: 0.73rem; font-weight: 600; font-family: var(--mono);
  border: 1px solid; letter-spacing: 0.03em; white-space: nowrap;
}
.pill svg { width: 12px; height: 12px; flex-shrink: 0; }
.pill-cyan   { color: var(--cyan);    border-color: rgba(56,189,248,0.30);   background: rgba(56,189,248,0.08); }
.pill-indigo { color: var(--indigo);  border-color: rgba(129,140,248,0.30);  background: rgba(129,140,248,0.08); }
.pill-emerald{ color: var(--emerald); border-color: rgba(16,185,129,0.30);   background: rgba(16,185,129,0.08); }
.pill-amber  { color: var(--amber);   border-color: rgba(245,158,11,0.30);   background: rgba(245,158,11,0.08); }
.pill-rose   { color: var(--rose);    border-color: rgba(244,63,94,0.30);    background: rgba(244,63,94,0.08); }
.pill-dim    { color: var(--text-dim); border-color: var(--border); background: transparent; }
.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--emerald); box-shadow: var(--glow-emerald);
  animation: livepulse 2s ease-in-out infinite;
  display: inline-block; flex-shrink: 0;
}
.live-dot.offline { background: var(--rose); box-shadow: var(--glow-rose); animation: none; }
@keyframes livepulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.75); }
}

/* Finding 11 & Audit E: Tightened offline banner with balanced ends */
.offline-banner {
  display: none; align-items: center; justify-content: space-between;
  background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.25);
  border-radius: 8px; padding: 8px 14px; margin-bottom: 16px;
  font-size: 0.78rem; color: var(--amber); font-weight: 500;
}
.offline-banner svg { width: 16px; height: 16px; stroke: var(--amber); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0; }
.offline-banner.visible { display: flex; }

/* Pass 3 Fix 7: Balanced KPI ribbon layout preventing orphan cards on tablets */
.kpi-ribbon {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px; margin-bottom: 20px;
}
@media (max-width: 1200px) {
  .kpi-ribbon { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 640px) {
  .kpi-ribbon { grid-template-columns: repeat(2, 1fr); gap: 10px; }
}

.kpi-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px;
  position: relative; overflow: hidden; transition: border-color 0.2s;
}
.kpi-card:hover { border-color: var(--border-hi); }
.kpi-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: var(--accent, var(--cyan)); opacity: 0.6;
}
.kpi-label {
  font-size: 0.72rem; color: var(--text-dim); font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.06em;
  margin-bottom: 6px; display: flex; align-items: center; gap: 6px;
}
.kpi-label svg { width: 13px; height: 13px; stroke: var(--accent, var(--cyan)); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.kpi-value { font-family: var(--mono); font-size: 1.55rem; font-weight: 600; color: var(--text-hi); line-height: 1.1; }
/* Pass 3 Fix 5: Prevents line-wrapping and overflow for long algorithm names */
.kpi-value--text { font-size: 1.05rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-sub { font-family: var(--mono); font-size: 0.72rem; color: var(--text-dim); margin-top: 5px; }

/* Pass 3 Fix 8: Lower breakpoint to 940px so 1024px preserves 2-column desktop layout */
.main-grid { display: grid; grid-template-columns: 1fr 390px; gap: 16px; margin-bottom: 16px; }
@media (max-width: 940px) { .main-grid { grid-template-columns: 1fr; } }
.bottom-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }

.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow);
}
.card-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 13px 18px 11px; border-bottom: 1px solid var(--border);
}
.card-title {
  font-size: 0.82rem; font-weight: 600; color: var(--text-hi);
  display: flex; align-items: center; gap: 8px;
  text-transform: uppercase; letter-spacing: 0.06em;
}
.card-title svg { width: 14px; height: 14px; stroke: var(--accent, var(--cyan)); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0; }
.card-body { padding: 16px 18px; }

/* Finding 4, 14 & Audit H: Tightened topology canvas height */
#topology-svg { width: 100%; height: 230px; display: block; }
.topo-label { font-family: var(--mono); font-size: 11px; fill: var(--text); font-weight: 500; }
.topo-label-hi { fill: var(--text-hi); }
.topo-label-dim { fill: var(--text-dim); font-size: 9.5px; }
.topo-link { stroke-dasharray: 6 4; animation: dashflow 1.2s linear infinite; }
.topo-link-active   { stroke: var(--cyan);   stroke-width: 2.5; opacity: 1; }
/* Finding 5: Legible standby link styling with indigo tint */
.topo-link-standby  { stroke: rgba(148,163,184,0.35); stroke-width: 1.5; opacity: 0.85; animation: none; stroke-dasharray: 4 6; }
.topo-link-b-active { stroke: var(--indigo); stroke-width: 2.5; opacity: 1; }
@keyframes dashflow { to { stroke-dashoffset: -20; } }

/* Finding 19 & Audit I: Outlined util label for crisp readability against link lines */
.util-label { font-family: var(--mono); font-size: 11px; fill: var(--text-hi); font-weight: 600; paint-order: stroke fill; stroke: var(--bg); stroke-width: 4px; stroke-linejoin: round; }

.seg-group { display: flex; gap: 6px; flex-direction: column; }
.seg-label { font-size: 0.72rem; color: var(--text-dim); font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.seg-label svg { width: 12px; height: 12px; stroke: var(--text-dim); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.seg-pills { display: flex; gap: 6px; }

/* Finding 7: Uniform seg-btn styling and sizing */
.seg-btn {
  flex: 1; min-width: 95px;
  background: var(--surface-2); border: 1px solid var(--border);
  color: var(--text); border-radius: 8px;
  padding: 8px 10px; font-family: var(--sans); font-size: 0.78rem; font-weight: 500;
  cursor: pointer; transition: all 0.18s; text-align: center; line-height: 1.25;
}
.seg-btn:hover { border-color: var(--border-hi); color: var(--text-hi); background: #1d2640; }
.seg-btn.sel-cyan   { background: rgba(56,189,248,0.12);  border-color: var(--cyan);   color: var(--cyan);   font-weight: 600; box-shadow: var(--glow-cyan); }
.seg-btn.sel-indigo { background: rgba(129,140,248,0.12); border-color: var(--indigo); color: var(--indigo); font-weight: 600; box-shadow: var(--glow-indigo); }
.seg-btn-sub { font-size: 0.67rem; color: var(--text-dim); margin-top: 2px; }

.divider { height: 1px; background: var(--border); margin: 14px 0; }

.link-gauge { margin-bottom: 14px; }
.gauge-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; font-size: 0.8rem; }
.gauge-label { display: flex; align-items: center; gap: 8px; font-weight: 500; }
.gauge-label svg { width: 13px; height: 13px; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.gauge-val { font-family: var(--mono); font-size: 0.78rem; color: var(--text); }
.bar-track { height: 6px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
/* Finding 20: Bar fill min-width handled cleanly */
.bar-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease, background-color 0.4s ease; min-width: 0; }
.bar-cyan   { background: var(--cyan); }
.bar-indigo { background: var(--indigo); }
.bar-amber  { background: var(--amber); }
.bar-rose   { background: var(--rose); }

/* Finding 10: Clear, readable gauge metadata */
.gauge-meta { display: flex; justify-content: space-between; margin-top: 5px; font-family: var(--mono); font-size: 0.73rem; color: var(--text); }

.server-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }

/* Finding 8: Flex column card with pinned actions */
.srv-card {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 8px; padding: 13px; transition: border-color 0.2s;
  display: flex; flex-direction: column;
}
.srv-card:hover { border-color: var(--border-hi); }
.srv-card.offline { border-color: rgba(244,63,94,0.25); background: rgba(244,63,94,0.04); }
.srv-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.srv-id { font-family: var(--mono); font-size: 0.88rem; font-weight: 600; color: var(--text-hi); display: flex; align-items: center; gap: 7px; }
.srv-id svg { width: 14px; height: 14px; stroke: var(--cyan); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.srv-id.offline svg { stroke: var(--rose); }
.status-beacon { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.beacon-up { background: var(--emerald); box-shadow: var(--glow-emerald); animation: livepulse 2.5s ease-in-out infinite; }
.beacon-dn { background: var(--rose); box-shadow: var(--glow-rose); }
.srv-ip { font-family: var(--mono); font-size: 0.68rem; color: var(--text-dim); margin-bottom: 6px; }
.srv-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin: 4px 0 8px; }
.srv-stat { font-family: var(--mono); font-size: 0.7rem; color: var(--text-dim); }
.srv-stat span { color: var(--text-hi); font-weight: 500; }
.srv-share-track { height: 4px; background: var(--surface); border-radius: 2px; overflow: hidden; margin-bottom: 8px; }
.srv-share-fill { height: 100%; background: var(--cyan); border-radius: 2px; transition: width 0.5s ease; }
.srv-share-fill.offline { background: var(--rose); }

/* Finding 8: Actions pinned to card bottom with equal min-width */
.srv-actions { display: flex; justify-content: flex-end; margin-top: auto; padding-top: 6px; }
.btn-micro {
  padding: 4px 10px; border-radius: 6px; font-size: 0.7rem; font-weight: 600;
  font-family: var(--sans); cursor: pointer; transition: all 0.18s; border: 1px solid;
  display: flex; align-items: center; justify-content: center; gap: 5px; min-width: 74px;
}
.btn-micro svg { width: 11px; height: 11px; fill: none; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }
.btn-crash   { color: var(--rose);    border-color: rgba(244,63,94,0.30);   background: rgba(244,63,94,0.06); }
.btn-crash:hover   { background: rgba(244,63,94,0.15);   border-color: var(--rose); }
.btn-recover { color: var(--emerald); border-color: rgba(16,185,129,0.30);  background: rgba(16,185,129,0.06); }
.btn-recover:hover { background: rgba(16,185,129,0.15);  border-color: var(--emerald); }

.gen-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.btn-gen {
  flex: 1; min-width: 88px;
  background: var(--surface-2); border: 1px solid var(--border);
  color: var(--text-hi); border-radius: 8px;
  padding: 9px 12px; font-family: var(--sans); font-size: 0.78rem; font-weight: 500;
  cursor: pointer; transition: all 0.18s; display: flex; align-items: center;
  justify-content: center; gap: 6px;
}
.btn-gen svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0; }
.btn-gen:hover { border-color: var(--border-hi); background: #1d2640; }
.btn-gen.primary { border-color: rgba(56,189,248,0.40); color: var(--cyan); }
.btn-gen.primary:hover { background: rgba(56,189,248,0.10); border-color: var(--cyan); box-shadow: var(--glow-cyan); }
.btn-gen.stream-on { border-color: var(--indigo); color: var(--indigo); background: rgba(129,140,248,0.10); animation: streampulse 1.5s ease-in-out infinite; }
@keyframes streampulse { 0%,100% { box-shadow: 0 0 0 0 rgba(129,140,248,0.4); } 70% { box-shadow: 0 0 0 6px rgba(129,140,248,0); } }

.gen-status-row { display: flex; align-items: center; justify-content: space-between; font-size: 0.76rem; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }
.gen-status-row .key { color: var(--text-dim); flex-shrink: 0; }
.gen-status-row .val { font-family: var(--mono); color: var(--text-hi); font-weight: 500; display: flex; align-items: center; gap: 5px; flex-wrap: wrap; justify-content: flex-end; }

/* Finding 13: Terminal height increased to 240px */
.log-terminal {
  background: #05080f; border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 14px; font-family: var(--mono); font-size: 0.74rem;
  color: #6b7a94; height: 240px; overflow-y: auto; line-height: 1.65;
}
.log-terminal::-webkit-scrollbar { width: 4px; }
.log-terminal::-webkit-scrollbar-thumb { background: var(--border-hi); border-radius: 4px; }
.log-line { display: flex; gap: 8px; align-items: baseline; }
.log-ts { color: var(--text-dim); flex-shrink: 0; }
.log-tag { font-weight: 600; flex-shrink: 0; }
.log-tag-lb { color: var(--cyan); }
.log-tag-te { color: var(--indigo); }
.log-tag-hc { color: var(--rose); }
.log-tag-ok { color: var(--emerald); }
.log-tag-tg { color: var(--amber); }
.log-msg { color: #8899b0; }

/* Finding 12: Clear button proper tap target & hover */
.btn-clear {
  background: var(--surface-2); border: 1px solid var(--border);
  font-family: var(--sans); font-size: 0.72rem; color: var(--text);
  cursor: pointer; padding: 5px 12px; border-radius: 6px; transition: all 0.15s;
}
.btn-clear:hover { color: var(--text-hi); border-color: var(--border-hi); background: #1d2640; }

.weight-badge { font-family: var(--mono); font-size: 0.65rem; font-weight: 600; padding: 2px 6px; border-radius: 4px; cursor: help; }
.wb-active { background: rgba(56,189,248,0.10); color: var(--cyan);     border: 1px solid rgba(56,189,248,0.25); }
.wb-dim    { background: var(--surface);         color: var(--text-dim); border: 1px solid var(--border); }
</style>
</head>
<body>
<div class="shell">

<!-- TOPBAR (Finding 16: unicode middle dot) -->
<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">
      <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
    </div>
    <div>
      <div class="topbar-title">SDN Network Operations Console</div>
      <div class="topbar-sub">OpenFlow 1.3 &#183; Ryu Controller &#183; Open vSwitch &#183; Mininet</div>
    </div>
  </div>
  <div class="topbar-right">
    <div id="conn-pill" class="pill pill-emerald">
      <span class="live-dot" id="live-dot"></span>
      <span id="conn-label">Connecting...</span>
    </div>
    <div class="pill pill-indigo" id="path-pill">
      <svg viewBox="0 0 24 24" style="stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;width:12px;height:12px"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/></svg>
      <span id="path-label">Path A</span>
    </div>
    <div class="pill pill-cyan" id="algo-pill">
      <svg viewBox="0 0 24 24" style="stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;width:12px;height:12px"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
      <span id="algo-label">Round-Robin</span>
    </div>
  </div>
</div>

<!-- OFFLINE BANNER (Simplified & Balanced) -->
<div class="offline-banner" id="offline-banner">
  <div style="display:flex;align-items:center;gap:10px">
    <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
    <span>Ryu controller offline at 127.0.0.1:8080 &#183; Autonomous simulation active</span>
  </div>
  <span class="pill pill-amber" style="padding:2px 8px;font-size:0.68rem">SIMULATION</span>
</div>

<!-- KPI RIBBON (Finding 1, 6, 15, 17) -->
<div class="kpi-ribbon">
  <div class="kpi-card" style="--accent:var(--cyan)">
    <div class="kpi-label"><svg viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>Total Dispatches</div>
    <div class="kpi-value" id="kpi-total">0</div>
    <div class="kpi-sub" id="kpi-success">0 served &#183; 4 active</div>
  </div>
  <div class="kpi-card" style="--accent:var(--indigo)">
    <div class="kpi-label"><svg viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>Throughput</div>
    <div class="kpi-value" id="kpi-rps">&#8212;</div>
    <div class="kpi-sub">10s rolling avg</div>
  </div>
  <div class="kpi-card" style="--accent:var(--emerald)">
    <div class="kpi-label"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>Avg Latency</div>
    <div class="kpi-value" id="kpi-avg">&#8212;</div>
    <div class="kpi-sub" id="kpi-p99">P99: &#8212;</div>
  </div>
  <div class="kpi-card" style="--accent:var(--cyan)">
    <div class="kpi-label"><svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>Jain's Fairness</div>
    <div class="kpi-value" id="kpi-jfi">&#8212;</div>
    <div class="kpi-sub" id="kpi-jfi-sub">Min 4 samples</div>
  </div>
  <div class="kpi-card" style="--accent:var(--amber)">
    <div class="kpi-label"><svg viewBox="0 0 24 24"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/></svg>TE Path</div>
    <div class="kpi-value kpi-value--text" id="kpi-te-path">Path A</div>
    <div class="kpi-sub" id="kpi-te-state">Nominal</div>
  </div>
  <div class="kpi-card" style="--accent:var(--indigo)">
    <div class="kpi-label"><svg viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>Algorithm</div>
    <div class="kpi-value kpi-value--text" id="kpi-algo-name">Round-Robin</div>
    <div class="kpi-sub" id="kpi-algo-desc">Cyclic</div>
  </div>
</div>

<!-- MAIN GRID -->
<div class="main-grid">
  <div style="display:flex;flex-direction:column;gap:16px">

    <!-- Topology Card (Finding 4, 5, 14, 19 & Audit H, I) -->
    <div class="card">
      <div class="card-header">
        <div class="card-title" style="--accent:var(--cyan)">
          <svg viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="9" r="3"/><path d="M6 9v6"/><path d="M9 9h9"/></svg>
          Network Topology
        </div>
        <div class="pill pill-dim" style="font-size:0.68rem">4-Switch Mesh &#183; OpenFlow 1.3</div>
      </div>
      <div class="card-body" style="padding:10px 18px 14px">
        <svg id="topology-svg" viewBox="0 22 700 196" xmlns="http://www.w3.org/2000/svg">
          <!-- Path A: s1-s2-s4 -->
          <line id="link-s1-s2" x1="213" y1="118" x2="368" y2="70"  class="topo-link topo-link-active"/>
          <line id="link-s2-s4" x1="422" y1="70"  x2="508" y2="118" class="topo-link topo-link-active"/>
          <!-- Path B: s1-s3-s4 -->
          <line id="link-s1-s3" x1="213" y1="146" x2="368" y2="184" class="topo-link topo-link-standby"/>
          <line id="link-s3-s4" x1="422" y1="184" x2="508" y2="146" class="topo-link topo-link-standby"/>
          <!-- s4 to backends -->
          <line x1="566" y1="132" x2="618" y2="50"  stroke="rgba(148,163,184,0.22)" stroke-width="1.2"/>
          <line x1="566" y1="132" x2="618" y2="96"  stroke="rgba(148,163,184,0.22)" stroke-width="1.2"/>
          <line x1="566" y1="132" x2="618" y2="142" stroke="rgba(148,163,184,0.22)" stroke-width="1.2"/>
          <line x1="566" y1="132" x2="618" y2="188" stroke="rgba(148,163,184,0.22)" stroke-width="1.2"/>
          <!-- s1 to clients -->
          <line x1="155" y1="120" x2="94"  y2="72"  stroke="rgba(148,163,184,0.22)" stroke-width="1.2"/>
          <line x1="155" y1="144" x2="94"  y2="182" stroke="rgba(148,163,184,0.22)" stroke-width="1.2"/>

          <!-- Client h1 -->
          <rect x="40" y="55"  width="54" height="34" rx="6" fill="#131b2e" stroke="rgba(148,163,184,0.20)" stroke-width="1.5"/>
          <text x="67" y="68"  class="topo-label topo-label-hi" text-anchor="middle">h1</text>
          <text x="67" y="81"  class="topo-label topo-label-dim" text-anchor="middle">10.0.0.1</text>
          <!-- Client h2 -->
          <rect x="40" y="165" width="54" height="34" rx="6" fill="#131b2e" stroke="rgba(148,163,184,0.20)" stroke-width="1.5"/>
          <text x="67" y="178" class="topo-label topo-label-hi" text-anchor="middle">h2</text>
          <text x="67" y="191" class="topo-label topo-label-dim" text-anchor="middle">10.0.0.2</text>

          <!-- s1 Ingress -->
          <rect x="155" y="105" width="58" height="54" rx="8" fill="#0d2040" stroke="rgba(56,189,248,0.45)" stroke-width="2"/>
          <text x="184" y="125" class="topo-label topo-label-hi" text-anchor="middle" font-size="12">s1</text>
          <text x="184" y="139" class="topo-label" text-anchor="middle" font-size="9.5">Ingress</text>
          <text x="184" y="151" class="topo-label topo-label-dim" text-anchor="middle" font-size="9">dpid:1</text>

          <!-- s2 Transit A -->
          <rect x="368" y="48" width="54" height="44" rx="8" id="node-s2" fill="#0d2040" stroke="rgba(56,189,248,0.45)" stroke-width="2"/>
          <text x="395" y="65"  class="topo-label topo-label-hi" text-anchor="middle" font-size="11">s2</text>
          <text x="395" y="77"  class="topo-label" text-anchor="middle" font-size="9">Path A</text>
          <text x="395" y="87"  class="topo-label topo-label-dim" text-anchor="middle" font-size="8.5">dpid:2</text>

          <!-- s3 Transit B -->
          <rect x="368" y="162" width="54" height="44" rx="8" id="node-s3" fill="#1a1040" stroke="rgba(129,140,248,0.35)" stroke-width="2"/>
          <text x="395" y="179" class="topo-label topo-label-hi" text-anchor="middle" font-size="11">s3</text>
          <text x="395" y="191" class="topo-label" text-anchor="middle" font-size="9">Path B</text>
          <text x="395" y="201" class="topo-label topo-label-dim" text-anchor="middle" font-size="8.5">dpid:3</text>

          <!-- s4 Egress -->
          <rect x="508" y="105" width="58" height="54" rx="8" fill="#0d2040" stroke="rgba(56,189,248,0.45)" stroke-width="2"/>
          <text x="537" y="125" class="topo-label topo-label-hi" text-anchor="middle" font-size="12">s4</text>
          <text x="537" y="139" class="topo-label" text-anchor="middle" font-size="9.5">Egress</text>
          <text x="537" y="151" class="topo-label topo-label-dim" text-anchor="middle" font-size="9">dpid:4</text>

          <!-- srv1 -->
          <rect id="bx-srv1" x="618" y="36" width="66" height="28" rx="5" fill="#131b2e" stroke="rgba(16,185,129,0.35)" stroke-width="1.5"/>
          <text x="651" y="49" class="topo-label topo-label-hi" text-anchor="middle" font-size="10.5">srv1</text>
          <text x="651" y="59" class="topo-label topo-label-dim" text-anchor="middle">10.0.0.11</text>
          <circle id="bd-srv1" cx="614" cy="50" r="4" fill="rgba(16,185,129,0.8)"/>

          <!-- srv2 -->
          <rect id="bx-srv2" x="618" y="82" width="66" height="28" rx="5" fill="#131b2e" stroke="rgba(16,185,129,0.35)" stroke-width="1.5"/>
          <text x="651" y="95" class="topo-label topo-label-hi" text-anchor="middle" font-size="10.5">srv2</text>
          <text x="651" y="105" class="topo-label topo-label-dim" text-anchor="middle">10.0.0.12</text>
          <circle id="bd-srv2" cx="614" cy="96" r="4" fill="rgba(16,185,129,0.8)"/>

          <!-- srv3 -->
          <rect id="bx-srv3" x="618" y="128" width="66" height="28" rx="5" fill="#131b2e" stroke="rgba(16,185,129,0.35)" stroke-width="1.5"/>
          <text x="651" y="141" class="topo-label topo-label-hi" text-anchor="middle" font-size="10.5">srv3</text>
          <text x="651" y="151" class="topo-label topo-label-dim" text-anchor="middle">10.0.0.13</text>
          <circle id="bd-srv3" cx="614" cy="142" r="4" fill="rgba(16,185,129,0.8)"/>

          <!-- srv4 -->
          <rect id="bx-srv4" x="618" y="174" width="66" height="28" rx="5" fill="#131b2e" stroke="rgba(16,185,129,0.35)" stroke-width="1.5"/>
          <text x="651" y="187" class="topo-label topo-label-hi" text-anchor="middle" font-size="10.5">srv4</text>
          <text x="651" y="197" class="topo-label topo-label-dim" text-anchor="middle">10.0.0.14</text>
          <circle id="bd-srv4" cx="614" cy="188" r="4" fill="rgba(16,185,129,0.8)"/>

          <!-- Utilization labels (Pass 3 Fix 6: symmetrically aligned above links) -->
          <text id="util-a" x="290" y="86"  class="util-label" text-anchor="middle">0.0%</text>
          <text id="util-b" x="290" y="154" class="util-label" text-anchor="middle">0.0%</text>
        </svg>
      </div>
    </div>

    <!-- Link Utilization Card (Pass 3 Fix 1: flex 1 to eliminate dead gap and align baseline) -->
    <div class="card" style="flex:1;display:flex;flex-direction:column">
      <div class="card-header">
        <div class="card-title" style="--accent:var(--indigo)">
          <svg viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          Transit Link Utilization
        </div>
        <div class="pill pill-dim" style="font-size:0.68rem">10 Mbps &#183; TE Limit 80%</div>
      </div>
      <div class="card-body" style="flex:1;display:flex;flex-direction:column;justify-content:space-between">
        <div>
          <div class="link-gauge">
            <div class="gauge-row">
              <div class="gauge-label" style="color:var(--cyan)">
                <svg viewBox="0 0 24 24" style="stroke:var(--cyan)"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/></svg>
                Path A &#183; s1 &#8594; s2 &#8594; s4
                <span id="tag-a" class="pill pill-cyan" style="padding:2px 8px;font-size:0.65rem;margin-left:4px">ACTIVE</span>
              </div>
              <div class="gauge-val"><span id="pa-rate">0 bps</span>&nbsp;<span style="color:var(--text-dim)">(<span id="pa-pct">0.0</span>%)</span></div>
            </div>
            <div class="bar-track"><div class="bar-fill bar-cyan" id="pa-bar" style="width:0%"></div></div>
            <div class="gauge-meta"><span>Cumulative: <span id="pa-cum" style="color:var(--text-hi)">&#8212;</span></span><span>Port 3 &#183; Transit s2</span></div>
          </div>
          <div class="link-gauge" style="margin-bottom:0">
            <div class="gauge-row">
              <div class="gauge-label" style="color:var(--indigo)">
                <svg viewBox="0 0 24 24" style="stroke:var(--indigo)"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/></svg>
                Path B &#183; s1 &#8594; s3 &#8594; s4
                <span id="tag-b" class="pill pill-dim" style="padding:2px 8px;font-size:0.65rem;margin-left:4px">STANDBY</span>
              </div>
              <div class="gauge-val"><span id="pb-rate">0 bps</span>&nbsp;<span style="color:var(--text-dim)">(<span id="pb-pct">0.0</span>%)</span></div>
            </div>
            <div class="bar-track"><div class="bar-fill bar-indigo" id="pb-bar" style="width:0%"></div></div>
            <div class="gauge-meta"><span>Cumulative: <span id="pb-cum" style="color:var(--text-hi)">&#8212;</span></span><span>Port 4 &#183; Transit s3</span></div>
          </div>
        </div>
        <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;font-size:0.76rem">
          <span style="color:var(--text-dim)">Adaptive TE Engine</span>
          <span id="te-state-label" style="color:var(--emerald);font-weight:600;font-family:var(--mono);font-size:0.74rem">Nominal (&lt;80%)</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Right sidebar -->
  <div style="display:flex;flex-direction:column;gap:16px">

    <!-- Scheduling Card (Finding 7: Simplified buttons and text) -->
    <div class="card">
      <div class="card-header">
        <div class="card-title" style="--accent:var(--cyan)">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49"/><path d="M6.34 6.34a10 10 0 0 0 0 14.14"/></svg>
          Policy &amp; Routing
        </div>
      </div>
      <div class="card-body">
        <div class="seg-group">
          <div class="seg-label"><svg viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>Load Balancing Algorithm</div>
          <div class="seg-pills">
            <button class="seg-btn sel-cyan" id="sbtn-rr" onclick="setAlgorithm('round_robin')">Round-Robin<div class="seg-btn-sub">Cyclic</div></button>
            <button class="seg-btn" id="sbtn-lc" onclick="setAlgorithm('least_connections')">Least-Conn<div class="seg-btn-sub">Min active</div></button>
            <button class="seg-btn" id="sbtn-w" onclick="setAlgorithm('weighted')">Weighted<div class="seg-btn-sub">1:2:1:2</div></button>
          </div>
        </div>
        <div class="divider"></div>
        <div class="seg-group">
          <div class="seg-label"><svg viewBox="0 0 24 24"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/></svg>Traffic Engineering Path</div>
          <div class="seg-pills">
            <button class="seg-btn sel-indigo" id="pbtn-auto" onclick="setPath('auto')">Adaptive<div class="seg-btn-sub">Auto reroute</div></button>
            <button class="seg-btn" id="pbtn-a" onclick="setPath('path_a')">Force Path A<div class="seg-btn-sub">Primary s2</div></button>
            <button class="seg-btn" id="pbtn-b" onclick="setPath('path_b')">Force Path B<div class="seg-btn-sub">Secondary s3</div></button>
          </div>
        </div>
        <div class="divider"></div>
        <!-- Audit G: Clean single-line TE threshold badge without clipping -->
        <div style="display:flex;align-items:center;justify-content:space-between;background:rgba(129,140,248,0.06);border:1px solid rgba(129,140,248,0.15);border-radius:6px;padding:6px 10px;font-size:0.72rem;font-family:var(--mono);color:var(--text)">
          <span style="color:var(--indigo);font-weight:600">TE THRESHOLDS</span>
          <span>&ge;80% reroute &#183; &lt;50% recover</span>
        </div>
      </div>
    </div>

    <!-- Traffic Generator (Finding 3) -->
    <div class="card">
      <div class="card-header">
        <div class="card-title" style="--accent:var(--amber)">
          <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          Traffic Generator
        </div>
        <div class="pill pill-dim" style="font-size:0.68rem">VIP 10.0.0.100</div>
      </div>
      <div class="card-body">
        <div class="gen-actions">
          <button class="btn-gen primary" onclick="sendTraffic(1)">
            <svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            Single (x1)
          </button>
          <button class="btn-gen primary" onclick="sendTraffic(8)">
            <svg viewBox="0 0 24 24"><polygon points="13 19 22 12 13 5 13 19"/><polygon points="2 19 11 12 2 5 2 19"/></svg>
            Burst x8
          </button>
          <button class="btn-gen primary" onclick="sendTraffic(20)">
            <svg viewBox="0 0 24 24"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg>
            Burst x20
          </button>
          <button class="btn-gen" id="stream-btn" onclick="toggleStream()">
            <svg viewBox="0 0 24 24" id="stream-icon" style="width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            Stream 2/s
          </button>
        </div>
        <div class="gen-status-row">
          <span class="key">State</span>
          <span class="val" id="gen-state">Idle</span>
        </div>
        <div class="gen-status-row">
          <span class="key">Last RTT</span>
          <span class="val" id="gen-lat">&#8212;</span>
        </div>
        <div class="gen-status-row" style="align-items:flex-start">
          <span class="key" style="margin-top:2px">Distribution</span>
          <div class="val" id="gen-dist" style="display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end">&#8212;</div>
        </div>
      </div>
    </div>

  </div>
</div>

<!-- BOTTOM GRID -->
<div class="bottom-grid">
  <!-- Backend Server Farm (Finding 8, 18) -->
  <div class="card" style="grid-column:1 / -1">
    <div class="card-header">
      <div class="card-title" style="--accent:var(--emerald)">
        <svg viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
        Backend Server Farm
      </div>
      <div style="font-size:0.73rem;color:var(--text-dim)">4 HTTP Backends &#183; 10s Health Probe</div>
    </div>
    <div class="card-body">
      <div class="server-grid" id="server-grid"></div>
    </div>
  </div>

  <!-- Telemetry & Event Audit Log (Finding 12, 13) -->
  <div class="card" style="grid-column:1 / -1">
    <div class="card-header">
      <div class="card-title" style="--accent:var(--text-dim)">
        <svg viewBox="0 0 24 24"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
        Telemetry &amp; Event Audit Log
      </div>
      <div style="display:flex;align-items:center;gap:10px">
        <div class="pill pill-dim" style="font-size:0.65rem">2s poll</div>
        <button class="btn-clear" onclick="clearLog()">Clear</button>
      </div>
    </div>
    <div class="card-body" style="padding:0 18px 16px">
      <div class="log-terminal" id="log-terminal"></div>
    </div>
  </div>
</div>
</div>

<script>
const ALGO_NAMES = { round_robin:'Round-Robin', least_connections:'Least-Conn', weighted:'Weighted' };
const ALGO_DESC  = { round_robin:'Cyclic', least_connections:'Min active', weighted:'1:2:1:2 capacity' };
let _streaming=false, _streamTimer=null, _prevReqs={}, _reqHistory=[], _activePath='path_a';

function ts(){return new Date().toTimeString().slice(0,8);}
function fmtRate(b){return b>=1e6?(b/1e6).toFixed(2)+' Mbps':b>=1e3?(b/1e3).toFixed(1)+' kbps':Math.round(b)+' bps';}
function fmtBytes(b){return b>=1048576?(b/1048576).toFixed(2)+' MB':b>=1024?(b/1024).toFixed(1)+' KB':b+' B';}
function jfi(c){const v=Object.values(c).map(Number).filter(x=>x>0);if(!v.length)return null;const n=v.length,s=v.reduce((a,b)=>a+b,0),sq=v.reduce((a,x)=>a+x*x,0);return sq?s*s/(n*sq):null;}
function clamp(v,a,b){return Math.max(a,Math.min(b,v));}
function setText(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}

/* Audit C: Cap terminal to max 100 entries to prevent memory/DOM bloat */
function log(tag,cls,msg){
  const box=document.getElementById('log-terminal');
  if(!box)return;
  while(box.children.length>=100){box.removeChild(box.firstChild);}
  const el=document.createElement('div');
  el.className='log-line';
  el.innerHTML='<span class="log-ts">['+ts()+']</span><span class="log-tag '+cls+'">['+tag+']</span><span class="log-msg">'+msg+'</span>';
  box.appendChild(el); box.scrollTop=box.scrollHeight;
}
/* Audit A: Clear resets audit terminal and telemetry counters */
async function clearLog(){
  const box=document.getElementById('log-terminal');
  if(box)box.innerHTML='';
  const gd=document.getElementById('gen-dist');if(gd)gd.innerHTML='\\u2014';
  _prevReqs={};_reqHistory=[];
  try{await fetch('/api/reset',{method:'POST'});}catch(e){}
  log('System','log-tag-ok','Audit log and telemetry counters reset.');
  poll();
}

function animatePacket(pts,col){
  const svg=document.getElementById('topology-svg'),ns='http://www.w3.org/2000/svg';
  const p=document.createElementNS(ns,'circle');
  p.setAttribute('r','5');p.setAttribute('fill',col||'#38bdf8');p.setAttribute('opacity','0');
  svg.appendChild(p);
  let step=0;
  function lerp(a,b,t){return a+(b-a)*t;}
  function tick(){
    if(step>=pts.length-1){try{svg.removeChild(p);}catch(e){}return;}
    const[x0,y0]=pts[step],[x1,y1]=pts[step+1];
    const dur=380;let start=null;
    function frame(now){
      if(!start)start=now;
      const t=clamp((now-start)/dur,0,1);
      p.setAttribute('cx',lerp(x0,x1,t));p.setAttribute('cy',lerp(y0,y1,t));
      p.setAttribute('opacity',t<0.1?t*10:t>0.9?(1-t)*10:1);
      if(t<1)requestAnimationFrame(frame);else{step++;tick();}
    }
    requestAnimationFrame(frame);
  }
  tick();
}

/* Updated coordinates matching the SVG viewBox */
const PKT_PATHS={
  path_a:{
    srv1:[[184,132],[395,70],[537,132],[651,50]],
    srv2:[[184,132],[395,70],[537,132],[651,96]],
    srv3:[[184,132],[395,70],[537,132],[651,142]],
    srv4:[[184,132],[395,70],[537,132],[651,188]]
  },
  path_b:{
    srv1:[[184,132],[395,184],[537,132],[651,50]],
    srv2:[[184,132],[395,184],[537,132],[651,96]],
    srv3:[[184,132],[395,184],[537,132],[651,142]],
    srv4:[[184,132],[395,184],[537,132],[651,188]]
  }
};
function firePackets(path,dest){
  const r=PKT_PATHS[path]||PKT_PATHS.path_a;
  animatePacket(r[dest]||r.srv1,path==='path_a'?'#38bdf8':'#818cf8');
}

/* Audit B: Single topo-link class name without duplicate tokens */
function updateTopologyLinks(p){
  const q=(id,cn,sw)=>{const e=document.getElementById(id);if(e){e.className.baseVal='topo-link '+cn;e.setAttribute('stroke-width',sw);}};
  if(p==='path_a'){
    q('link-s1-s2','topo-link-active','2.5');q('link-s2-s4','topo-link-active','2.5');
    q('link-s1-s3','topo-link-standby','1.5');q('link-s3-s4','topo-link-standby','1.5');
    const ta=document.getElementById('tag-a'),tb=document.getElementById('tag-b');
    if(ta){ta.className='pill pill-cyan';ta.textContent='ACTIVE';}
    if(tb){tb.className='pill pill-dim';tb.textContent='STANDBY';}
  } else {
    q('link-s1-s2','topo-link-standby','1.5');q('link-s2-s4','topo-link-standby','1.5');
    q('link-s1-s3','topo-link-b-active','2.5');q('link-s3-s4','topo-link-b-active','2.5');
    const ta=document.getElementById('tag-a'),tb=document.getElementById('tag-b');
    if(ta){ta.className='pill pill-dim';ta.textContent='STANDBY';}
    if(tb){tb.className='pill pill-indigo';tb.textContent='ACTIVE';}
  }
  _activePath=p;
}

function renderServers(backends,totalReqs,activeConns,algo){
  const grand=Object.values(totalReqs).reduce((a,b)=>a+b,0);
  let html='';
  backends.forEach(b=>{
    const up=b.healthy,reqs=totalReqs[b.id]||0,conns=activeConns[b.id]||0;
    const pct=grand>0?((reqs/grand)*100).toFixed(1):'0.0';
    /* Finding 18: Added tooltip to weight badge */
    const wb=algo==='weighted'
      ?'<span class="weight-badge wb-active" title="Load balancing weight: capacity multiplier">w='+b.weight+'</span>'
      :'<span class="weight-badge wb-dim" title="Load balancing weight: capacity multiplier">w='+b.weight+'</span>';
    const act=up
      ?'<button class="btn-micro btn-crash" onclick="toggleServer(\\''+b.id+'\\',false)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>Crash</button>'
      :'<button class="btn-micro btn-recover" onclick="toggleServer(\\''+b.id+'\\',true)"><svg viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>Restore</button>';
    html+='<div class="srv-card '+(up?'':'offline')+'">'
      +'<div class="srv-header"><div class="srv-id '+(up?'':'offline')+'"><svg viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>'+b.id+' '+wb+'</div>'
      +'<span class="status-beacon '+(up?'beacon-up':'beacon-dn')+'"></span></div>'
      +'<div class="srv-ip">'+b.ip+':'+(b.port||80)+' &#183; '+(b.mac||'N/A')+'</div>'
      +'<div class="srv-stats"><div class="srv-stat">Served: <span>'+reqs+'</span></div><div class="srv-stat">Share: <span>'+pct+'%</span></div><div class="srv-stat">Active: <span>'+conns+'</span></div><div class="srv-stat">Status: <span style="color:'+(up?'var(--emerald)':'var(--rose)')+';">'+(up?'ONLINE':'OFFLINE')+'</span></div></div>'
      +'<div class="srv-share-track"><div class="srv-share-fill '+(up?'':'offline')+'" style="width:'+pct+'%"></div></div>'
      +'<div class="srv-actions">'+act+'</div></div>';
  });
  document.getElementById('server-grid').innerHTML=html;
  ['srv1','srv2','srv3','srv4'].forEach(sid=>{
    const bd=document.getElementById('bd-'+sid),bx=document.getElementById('bx-'+sid);
    if(!bd||!bx)return;
    const srv=backends.find(b=>b.id===sid);
    if(srv){const up=srv.healthy;bd.setAttribute('fill',up?'rgba(16,185,129,0.85)':'rgba(244,63,94,0.85)');bx.setAttribute('stroke',up?'rgba(16,185,129,0.35)':'rgba(244,63,94,0.30)');}
  });
}

async function poll(){
  try{
    const d=await fetch('/api/data').then(r=>r.json());
    const off=d.sim_mode;
    document.getElementById('offline-banner').classList.toggle('visible',!!off);
    const ldot=document.getElementById('live-dot'),cpill=document.getElementById('conn-pill');
    if(off){ldot.className='live-dot offline';cpill.className='pill pill-amber';setText('conn-label','Simulation Mode');}
    else{ldot.className='live-dot';cpill.className='pill pill-emerald';setText('conn-label','Live \\u2014 Ryu Connected');}
    const algo=d.algorithm||'round_robin';
    setText('algo-label',ALGO_NAMES[algo]||algo);setText('kpi-algo-name',ALGO_NAMES[algo]||algo);setText('kpi-algo-desc',ALGO_DESC[algo]||'');
    ['rr','lc','w'].forEach(k=>document.getElementById('sbtn-'+k).className='seg-btn');
    if(algo==='round_robin')document.getElementById('sbtn-rr').className='seg-btn sel-cyan';
    else if(algo==='least_connections')document.getElementById('sbtn-lc').className='seg-btn sel-cyan';
    else document.getElementById('sbtn-w').className='seg-btn sel-cyan';
    const path=d.preferred_path||'path_a',manLock=d.manual_override;
    setText('path-label',(path==='path_a'?'Path A':'Path B')+(manLock?' [Locked]':' [Auto]'));
    setText('kpi-te-path',path==='path_a'?'Path A':'Path B');
    updateTopologyLinks(path);
    ['pbtn-auto','pbtn-a','pbtn-b'].forEach(id=>document.getElementById(id).className='seg-btn');
    if(!manLock)document.getElementById('pbtn-auto').className='seg-btn sel-indigo';
    else if(manLock==='path_a')document.getElementById('pbtn-a').className='seg-btn sel-indigo';
    else document.getElementById('pbtn-b').className='seg-btn sel-indigo';
    const ls=d.link_stats||{},pa=ls.path_a||{bps:0,ratio:0,tx_bytes:0},pb=ls.path_b||{bps:0,ratio:0,tx_bytes:0};
    const paPct=Math.min(100,(pa.ratio||0)*100),pbPct=Math.min(100,(pb.ratio||0)*100);
    setText('pa-rate',fmtRate(pa.bps||0));setText('pa-pct',(pa.bps>0&&paPct<0.1)?'< 0.1':paPct.toFixed(1));
    /* Finding 9: Show dash when no traffic */
    setText('pa-cum',pa.tx_bytes>0?fmtBytes(pa.tx_bytes):'\\u2014');
    const paBar=document.getElementById('pa-bar');
    /* Finding 20: 4px min-width when non-zero */
    paBar.style.width=paPct+'%';
    paBar.style.minWidth=paPct>0?'4px':'0px';
    paBar.className='bar-fill '+(paPct>=80?'bar-rose':paPct>=50?'bar-amber':'bar-cyan');
    setText('pb-rate',fmtRate(pb.bps||0));setText('pb-pct',(pb.bps>0&&pbPct<0.1)?'< 0.1':pbPct.toFixed(1));
    /* Finding 9: Show dash when no traffic */
    setText('pb-cum',pb.tx_bytes>0?fmtBytes(pb.tx_bytes):'\\u2014');
    const pbBar=document.getElementById('pb-bar');
    /* Finding 20: 4px min-width when non-zero */
    pbBar.style.width=pbPct+'%';
    pbBar.style.minWidth=pbPct>0?'4px':'0px';
    pbBar.className='bar-fill '+(pbPct>=80?'bar-rose':pbPct>=50?'bar-amber':'bar-indigo');

    /* Finding 2: Avoid misleading 0.0% when bps is active */
    setText('util-a',(pa.bps>0&&paPct<0.1)?'< 0.1%':(paPct.toFixed(1)+'%'));
    setText('util-b',(pb.bps>0&&pbPct<0.1)?'< 0.1%':(pbPct.toFixed(1)+'%'));

    const maxU=Math.max(paPct,pbPct),teEl=document.getElementById('te-state-label');
    if(maxU>=80){teEl.textContent='Saturated ('+maxU.toFixed(1)+'%) \\u2014 Rerouted';teEl.style.color='var(--rose)';setText('kpi-te-state','Saturated');}
    else if(maxU>=50){teEl.textContent='Elevated ('+maxU.toFixed(1)+'%) \\u2014 Monitoring';teEl.style.color='var(--amber)';setText('kpi-te-state','Elevated');}
    else{teEl.textContent='Nominal (<80%)';teEl.style.color='var(--emerald)';setText('kpi-te-state','Nominal');}

    const backends=d.backends||[],totalReqs=d.total_requests||{},activeConns=d.active_connections||{};
    renderServers(backends,totalReqs,activeConns,algo);
    if(Object.keys(_prevReqs).length>0)backends.forEach(b=>{const c=totalReqs[b.id]||0,pr=_prevReqs[b.id]||0;if(c>pr)log('LoadBalancer','log-tag-lb',b.id+' +'+(c-pr)+' req (total:'+c+')');});
    _prevReqs={...totalReqs};
    const grand=d.total_dispatched||Object.values(totalReqs).reduce((a,b)=>a+b,0);
    setText('kpi-total',grand);

    /* Finding 1: Update kpi-success dynamically */
    const upCount=backends.filter(b=>b.healthy).length;
    setText('kpi-success',grand+' served \\u00B7 '+upCount+' active');

    /* Finding 15 & Audit F: Require at least 4 dispatches and color-code JFI sub-label */
    const jfiSubEl=document.getElementById('kpi-jfi-sub');
    if(grand>=4){
      const j=jfi(totalReqs);
      if(j!==null){
        setText('kpi-jfi',j.toFixed(4));
        if(j>=0.98){
          if(jfiSubEl){jfiSubEl.textContent='Optimal';jfiSubEl.style.color='var(--emerald)';}
        }else if(j>=0.85){
          if(jfiSubEl){jfiSubEl.textContent='Balanced';jfiSubEl.style.color='var(--cyan)';}
        }else{
          if(jfiSubEl){jfiSubEl.textContent='Asymmetric';jfiSubEl.style.color='var(--amber)';}
        }
      }else{
        setText('kpi-jfi','\\u2014');
        if(jfiSubEl){jfiSubEl.textContent='Min 4 samples';jfiSubEl.style.color='var(--text-dim)';}
      }
    }else{
      setText('kpi-jfi','\\u2014');
      if(jfiSubEl){jfiSubEl.textContent='Min 4 samples';jfiSubEl.style.color='var(--text-dim)';}
    }

    /* Audit D: Stable 10s rolling average throughput window */
    _reqHistory.push({t:Date.now(),count:grand});
    while(_reqHistory.length>1&&(Date.now()-_reqHistory[0].t)>10000)_reqHistory.shift();
    if(_reqHistory.length>=2){
      const fst=_reqHistory[0],lst=_reqHistory[_reqHistory.length-1];
      const dt=(lst.t-fst.t)/1000,dq=lst.count-fst.count;
      if(dt>0.5){
        const rps=dq/dt;
        setText('kpi-rps',rps>0?rps.toFixed(1):(grand>0?'0.0':'\\u2014'));
      }
    }else if(grand===0){
      setText('kpi-rps','\\u2014');
    }

    if(d.latencies&&d.latencies.length>0){
      const lats=d.latencies,avg=(lats.reduce((a,b)=>a+b,0)/lats.length).toFixed(1);
      const sorted=[...lats].sort((a,b)=>a-b),p99=sorted[Math.floor(sorted.length*0.99)]||sorted[sorted.length-1];
      setText('kpi-avg',avg+' ms');setText('kpi-p99','P99: '+(p99||0).toFixed(1)+' ms');
    }
  }catch(e){}
}
setInterval(poll,2000);
log('System','log-tag-ok','SDN Operations Console \\u2014 telemetry active (2s interval).');
poll();

async function setAlgorithm(algo){
  try{await fetch('/api/set-algo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({algorithm:algo})});log('LoadBalancer','log-tag-lb','Policy: '+(ALGO_NAMES[algo]||algo));}
  catch(e){log('Error','log-tag-hc','Algorithm switch error: '+e.message);}
  poll();
}
async function setPath(path){
  const names={auto:'Adaptive',path_a:'Force Path A',path_b:'Force Path B'};
  try{await fetch('/api/set-path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:path})});log('TrafficEng','log-tag-te','Path: '+(names[path]||path));}
  catch(e){log('Error','log-tag-hc','Path error: '+e.message);}
  poll();
}
async function sendTraffic(count){
  const stEl=document.getElementById('gen-state');
  stEl.textContent='Sending '+count+'...';stEl.style.color='var(--amber)';
  const t0=performance.now();
  try{
    const d=await fetch('/api/generate-traffic',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:count})}).then(r=>r.json());
    const el=(performance.now()-t0).toFixed(1);
    if(d.status==='success'){
      stEl.textContent='OK \\u2014 '+count+' dispatched';stEl.style.color='var(--emerald)';
      document.getElementById('gen-lat').textContent=el+' ms';
      const bd=d.breakdown||{},distStr=Object.entries(bd).map(([k,v])=>k+':'+v).join('  ');
      const pills=Object.entries(bd).map(([k,v])=>'<span class="pill pill-cyan" style="font-size:0.68rem;padding:2px 7px">'+k+' \\xd7'+v+'</span>').join('');
      document.getElementById('gen-dist').innerHTML=pills||'\\u2014';
      const srvDest=Object.keys(bd)[0]||'srv1';
      for(let i=0;i<Math.min(count,4);i++)setTimeout(()=>firePackets(_activePath,d.servers&&d.servers[i]||srvDest),i*130);
      log('Client','log-tag-tg','Dispatched '+count+' req ['+distStr+'] RTT:'+el+'ms');
    }else{stEl.textContent='Error';stEl.style.color='var(--rose)';log('Error','log-tag-hc',d.message||'unknown');}
  }catch(e){stEl.textContent='Network error';stEl.style.color='var(--rose)';log('Error','log-tag-hc',e.message);}
  poll();
}

/* Finding 3: Consistent SVG triangle icon with proper fill/stroke */
function toggleStream(){
  const btn=document.getElementById('stream-btn');
  if(_streaming){
    clearInterval(_streamTimer);_streaming=false;
    btn.className='btn-gen';
    btn.innerHTML='<svg viewBox="0 0 24 24" style="width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round"><polygon points="5 3 19 12 5 21 5 3"/></svg> Stream 2/s';
    log('Client','log-tag-ok','Stream stopped.');
  }else{
    _streaming=true;btn.className='btn-gen stream-on';
    btn.innerHTML='<svg viewBox="0 0 24 24" style="width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> Stop Stream';
    log('Client','log-tag-tg','Stream active (2 req/s).');
    sendTraffic(2);_streamTimer=setInterval(()=>sendTraffic(2),1500);
  }
}
async function toggleServer(bid,healthy){
  log('HealthChecker','log-tag-hc',(healthy?'Restoring ':'Crashing ')+bid+'...');
  try{await fetch('/api/toggle-server',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backend_id:bid,healthy:healthy})});
  log('HealthChecker',healthy?'log-tag-ok':'log-tag-hc',bid+' is now '+(healthy?'ONLINE':'OFFLINE'));}
  catch(e){log('Error','log-tag-hc',e.message);}
  poll();
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/data")
def get_data():
    live = _ryu_available()
    combined = {
        "sim_mode": not live,
        "algorithm": _sim["algorithm"],
        "preferred_path": _sim["preferred_path"],
        "manual_override": _sim["manual_override"],
        "backends": [],
        "total_requests": {},
        "active_connections": {},
        "link_stats": {},
        "total_dispatched": _sim["total_dispatched"],
        "latencies": list(_sim["latencies"][-80:]),
    }
    if live:
        try:
            with urllib.request.urlopen(f"{RYU_REST_BASE}/stats", timeout=2) as r:
                stats = json.loads(r.read().decode())
                combined.update({
                    "algorithm": stats.get("algorithm", combined["algorithm"]),
                    "preferred_path": stats.get("preferred_path", combined["preferred_path"]),
                    "backends": stats.get("backends", []),
                    "total_requests": stats.get("total_requests", {}),
                    "active_connections": stats.get("active_connections", {}),
                })
        except Exception:
            pass
        try:
            with urllib.request.urlopen(f"{RYU_REST_BASE}/telemetry", timeout=2) as r:
                te = json.loads(r.read().decode())
                combined["link_stats"] = te.get("link_utilization", {})
                te_s = te.get("traffic_engineering", {})
                if "preferred_path" in te_s:
                    combined["preferred_path"] = te_s["preferred_path"]
                if "manual_override" in te_s:
                    combined["manual_override"] = te_s["manual_override"]
        except Exception:
            pass
    if not combined["backends"]:
        with _sim_lock:
            combined["backends"] = copy.deepcopy(_sim["backends"])
            combined["total_requests"] = dict(_sim["total_requests"])
            combined["active_connections"] = dict(_sim["active_connections"])
            cap = _sim["link_capacity_bps"]
            combined["link_stats"] = {
                "path_a": {
                    "bps": _sim["path_a_bps"],
                    "ratio": _sim["path_a_bps"] / cap,
                    "tx_bytes": _sim["path_a_tx_total"],
                },
                "path_b": {
                    "bps": _sim["path_b_bps"],
                    "ratio": _sim["path_b_bps"] / cap,
                    "tx_bytes": _sim["path_b_tx_total"],
                },
            }
    return jsonify(combined)


@app.route("/api/set-algo", methods=["POST"])
def set_algo():
    payload = request.get_json(silent=True) or {}
    algo = payload.get("algorithm", "round_robin")
    if _ryu_available():
        req = urllib.request.Request(
            f"{RYU_REST_BASE}/algorithm",
            json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                return jsonify(json.loads(r.read().decode())), r.status
        except Exception:
            pass
    with _sim_lock:
        _sim["algorithm"] = algo
        _sim["rr_index"] = 0
        _rebuild_pool()
    return jsonify({"status": "success", "algorithm": algo})


@app.route("/api/set-path", methods=["POST"])
def set_path():
    payload = request.get_json(silent=True) or {}
    path = payload.get("path", "auto")
    if _ryu_available():
        req = urllib.request.Request(
            f"{RYU_REST_BASE}/traffic-engineer/path",
            json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                return jsonify(json.loads(r.read().decode())), r.status
        except Exception:
            pass
    with _sim_lock:
        if path == "auto":
            _sim["manual_override"] = False
        else:
            _sim["manual_override"] = path
            _sim["preferred_path"] = path
    return jsonify({"status": "success", "path": path})


@app.route("/api/generate-traffic", methods=["POST"])
def generate_traffic():
    payload = request.get_json(silent=True) or {}
    count = max(1, min(50, int(payload.get("count", 4))))
    if _ryu_available():
        try:
            out = subprocess.check_output(["pgrep", "-f", "mininet:h1"]).decode().strip().split()
            if out:
                h1_pid = out[0]
                snip = (
                    "import urllib.request,json\nresults=[]\n"
                    f"for _ in range({count}):\n"
                    " try:\n"
                    "  with urllib.request.urlopen('http://10.0.0.100/',timeout=2) as r:\n"
                    "   d=json.loads(r.read().decode())\n"
                    "   results.append(d.get('server_id','unknown'))\n"
                    " except: results.append('error')\n"
                    "print(json.dumps(results))\n"
                )
                raw = subprocess.check_output(
                    ["sudo", "mnexec", "-a", h1_pid, "python3", "-c", snip], timeout=12
                ).decode().strip()
                servers = json.loads(raw)
                bd = dict(collections.Counter(servers))
                return jsonify({"status": "success", "count": count, "servers": servers, "breakdown": bd})
        except Exception:
            pass
    servers = _sim_dispatch(count)
    bd = dict(collections.Counter(servers))
    return jsonify({"status": "success", "count": count, "servers": servers, "breakdown": bd})


@app.route("/api/toggle-server", methods=["POST"])
def toggle_server():
    payload = request.get_json(silent=True) or {}
    b_id = payload.get("backend_id")
    healthy = payload.get("healthy")
    if not b_id or healthy is None:
        return jsonify({"status": "error", "message": "Missing backend_id or healthy"}), 400
    if _ryu_available():
        req = urllib.request.Request(
            f"{RYU_REST_BASE}/backend/health",
            json.dumps({"backend_id": b_id, "healthy": bool(healthy)}).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return jsonify(json.loads(r.read().decode())), r.status
        except Exception:
            pass
    with _sim_lock:
        for b in _sim["backends"]:
            if b["id"] == b_id:
                b["healthy"] = bool(healthy)
                break
        _rebuild_pool()
    return jsonify({"status": "success", "backend_id": b_id, "healthy": bool(healthy)})


@app.route("/api/reset", methods=["POST"])
def reset_sim():
    with _sim_lock:
        _sim["total_requests"] = {"srv1": 0, "srv2": 0, "srv3": 0, "srv4": 0}
        _sim["active_connections"] = {"srv1": 0, "srv2": 0, "srv3": 0, "srv4": 0}
        _sim["path_a_bytes"] = 0
        _sim["path_b_bytes"] = 0
        _sim["path_a_tx_total"] = 0
        _sim["path_b_tx_total"] = 0
        _sim["path_a_bps"] = 0.0
        _sim["path_b_bps"] = 0.0
        _sim["total_dispatched"] = 0
        _sim["latencies"] = []
        _sim["rr_index"] = 0
        _sim["preferred_path"] = "path_a"
        _sim["manual_override"] = False
        _sim["te_congested"] = False
        _sim["te_hold_cycles"] = 0
        for b in _sim["backends"]:
            b["healthy"] = True
        _rebuild_pool()
    return jsonify({"status": "success"})


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8081))
    print(f"[*] SDN Operations Console starting on http://0.0.0.0:{port}")
    print(f"    Ryu REST: {RYU_REST_BASE}")
    app.run(host="0.0.0.0", port=port, threaded=True)
