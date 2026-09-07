#!/usr/bin/env python3
"""
Live Web Telemetry & Management Dashboard
Provides real-time visualization of backend load distribution, link bandwidth utilization,
health states, and allows runtime switching of load balancing algorithms and transit paths.
"""

import json
import logging
import os
import urllib.request
import urllib.error
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

RYU_REST_BASE = "http://127.0.0.1:8080/api"

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SDN Load Balancer & Traffic Engineering Telemetry</title>
    <style>
        :root {
            --bg: #0d1117;
            --surface: #161b22;
            --surface-border: #30363d;
            --text: #c9d1d9;
            --text-bright: #f0f6fc;
            --primary: #58a6ff;
            --success: #3fb950;
            --warning: #d29922;
            --danger: #f85149;
            --purple: #bc8cff;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 24px;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--surface-border);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }
        h1 { color: var(--text-bright); font-size: 1.5rem; font-weight: 600; }
        .badge {
            background: #1f6feb22;
            border: 1px solid var(--primary);
            color: var(--primary);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }
        .card {
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        .card h2 {
            font-size: 1.1rem;
            color: var(--text-bright);
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .btn-group {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }
        button {
            background: #21262d;
            border: 1px solid var(--surface-border);
            color: var(--text);
            padding: 8px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 500;
            transition: all 0.2s;
        }
        button:hover { background: #30363d; color: var(--text-bright); }
        button.active { background: var(--primary); color: #0d1117; font-weight: 600; border-color: var(--primary); }
        .server-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #21262d;
        }
        .server-item:last-child { border-bottom: none; }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }
        .status-up { background: var(--success); box-shadow: 0 0 8px var(--success); }
        .status-down { background: var(--danger); box-shadow: 0 0 8px var(--danger); }
        .bar-container {
            width: 100%;
            height: 10px;
            background: #21262d;
            border-radius: 5px;
            overflow: hidden;
            margin: 6px 0;
        }
        .bar-fill { height: 100%; transition: width 0.4s ease; border-radius: 5px; }
        .bar-primary { background: var(--primary); }
        .bar-warning { background: var(--warning); }
        .bar-danger { background: var(--danger); }
        .metric-row {
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            margin-bottom: 4px;
        }
        .log-box {
            background: #090d13;
            border: 1px solid var(--surface-border);
            border-radius: 6px;
            padding: 12px;
            font-family: monospace;
            font-size: 0.85rem;
            color: #8b949e;
            height: 90px;
            overflow-y: auto;
        }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>SDN Load Balancer & Traffic Engineering Telemetry</h1>
            <p style="font-size: 0.85rem; color: #8b949e; margin-top: 4px;">OpenFlow 1.3 Control Plane &amp; Data Center Traffic Optimization</p>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
            <span class="badge" id="active-algo-badge">Algorithm: Round-Robin</span>
            <span class="badge" style="border-color: var(--purple); color: var(--purple);" id="active-path-badge">Active Path: Path A</span>
        </div>
    </header>

    <div class="grid">
        <!-- 1. Algorithm Selection -->
        <div class="card">
            <h2>Load Balancing Policy</h2>
            <p style="font-size: 0.85rem; color: #8b949e;">Select runtime distribution algorithm for incoming client flows:</p>
            <div class="btn-group">
                <button id="btn-rr" onclick="setAlgorithm('round_robin')" class="active">Round-Robin</button>
                <button id="btn-lc" onclick="setAlgorithm('least_connections')">Least-Connections</button>
                <button id="btn-w" onclick="setAlgorithm('weighted')">Weighted (1:2:1:2)</button>
            </div>
            <div style="margin-top: 18px;">
                <p style="font-size: 0.85rem; color: #8b949e;">Manual Path Override (Traffic Engineering):</p>
                <div class="btn-group">
                    <button id="btn-path-a" onclick="setPath('path_a')">Force Path A (Upper)</button>
                    <button id="btn-path-b" onclick="setPath('path_b')">Force Path B (Lower)</button>
                </div>
            </div>
        </div>

        <!-- 2. Path Bandwidth Utilization -->
        <div class="card">
            <h2>Transit Link Telemetry (10 Mbps Links)</h2>
            <div style="margin-bottom: 14px;">
                <div class="metric-row">
                    <span>Path A (s1 &harr; s2 &harr; s4)</span>
                    <span id="path-a-text">0.0 kbps (0.0%)</span>
                </div>
                <div class="bar-container">
                    <div class="bar-fill bar-primary" id="path-a-bar" style="width: 0%;"></div>
                </div>
            </div>
            <div>
                <div class="metric-row">
                    <span>Path B (s1 &harr; s3 &harr; s4)</span>
                    <span id="path-b-text">0.0 kbps (0.0%)</span>
                </div>
                <div class="bar-container">
                    <div class="bar-fill bar-primary" id="path-b-bar" style="width: 0%;"></div>
                </div>
            </div>
            <div style="margin-top: 14px;">
                <div class="metric-row">
                    <span style="color: #8b949e;">TE Trigger Status:</span>
                    <span id="te-status" style="color: var(--success); font-weight: 600;">Nominal</span>
                </div>
            </div>
        </div>

        <!-- 3. Traffic Engineering Log -->
        <div class="card">
            <h2>Telemetry Events</h2>
            <div class="log-box" id="event-log">
                [System] Telemetry stream initialized.<br>
                [TE] Monitoring link utilization thresholds...
            </div>
        </div>
    </div>

    <!-- 4. Backend Server Pool -->
    <div class="card">
        <h2>Backend Application Server Pool (Virtual IP: 10.0.0.100:80)</h2>
        <div id="backend-list">
            Loading backend statuses...
        </div>
    </div>

    <script>
        async function fetchTelemetry() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();

                // Update Algorithm & Path Badges
                const algoNames = {
                    "round_robin": "Round-Robin",
                    "least_connections": "Least-Connections",
                    "weighted": "Weighted (1:2:1:2)"
                };
                document.getElementById('active-algo-badge').innerText = 'Algorithm: ' + (algoNames[data.algorithm] || data.algorithm);
                document.getElementById('active-path-badge').innerText = 'Active Path: ' + (data.preferred_path === 'path_a' ? 'Path A (Upper)' : 'Path B (Lower)');

                // Update active buttons
                document.getElementById('btn-rr').className = data.algorithm === 'round_robin' ? 'active' : '';
                document.getElementById('btn-lc').className = data.algorithm === 'least_connections' ? 'active' : '';
                document.getElementById('btn-w').className = data.algorithm === 'weighted' ? 'active' : '';

                // Update Link Telemetry
                const linkStats = data.link_stats || {};
                const pa = linkStats.path_a || { bps: 0, ratio: 0 };
                const pb = linkStats.path_b || { bps: 0, ratio: 0 };

                const paPct = Math.min(100, (pa.ratio * 100)).toFixed(1);
                const pbPct = Math.min(100, (pb.ratio * 100)).toFixed(1);

                document.getElementById('path-a-text').innerText = `${(pa.bps / 1000).toFixed(1)} kbps (${paPct}%)`;
                document.getElementById('path-a-bar').style.width = paPct + '%';
                document.getElementById('path-a-bar').className = 'bar-fill ' + (paPct > 75 ? 'bar-danger' : paPct > 50 ? 'bar-warning' : 'bar-primary');

                document.getElementById('path-b-text').innerText = `${(pb.bps / 1000).toFixed(1)} kbps (${pbPct}%)`;
                document.getElementById('path-b-bar').style.width = pbPct + '%';
                document.getElementById('path-b-bar').className = 'bar-fill ' + (pbPct > 75 ? 'bar-danger' : pbPct > 50 ? 'bar-warning' : 'bar-primary');

                // Update Backend Server List
                const backends = data.backends || [];
                const reqCounts = data.total_requests || {};
                const activeConns = data.active_connections || {};

                let html = '';
                backends.forEach(b => {
                    const statusClass = b.healthy ? 'status-up' : 'status-down';
                    const statusText = b.healthy ? 'ONLINE' : 'OFFLINE';
                    const totalReq = reqCounts[b.id] || 0;
                    const conns = activeConns[b.id] || 0;
                    html += `
                    <div class="server-item">
                        <div>
                            <span class="status-dot ${statusClass}"></span>
                            <strong style="color: var(--text-bright);">${b.id}</strong>
                            <span style="color: #8b949e; font-size: 0.85rem; margin-left: 8px;">(${b.ip}:${b.port}) | Weight: ${b.weight}</span>
                        </div>
                        <div style="display: flex; gap: 20px; align-items: center; font-size: 0.85rem;">
                            <span>Active Conns: <strong>${conns}</strong></span>
                            <span>Total Served: <strong>${totalReq}</strong></span>
                            <span style="font-weight: 600; color: ${b.healthy ? 'var(--success)' : 'var(--danger)'};">${statusText}</span>
                        </div>
                    </div>`;
                });
                document.getElementById('backend-list').innerHTML = html;

            } catch (err) {
                console.error("Failed to fetch telemetry:", err);
            }
        }

        async function setAlgorithm(algo) {
            await fetch('/api/set-algo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ algorithm: algo })
            });
            fetchTelemetry();
        }

        async function setPath(path) {
            await fetch('/api/set-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path })
            });
            fetchTelemetry();
        }

        setInterval(fetchTelemetry, 2000);
        fetchTelemetry();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/data")
def get_dashboard_data():
    """Proxy query to Ryu Controller REST API."""
    stats_url = f"{RYU_REST_BASE}/stats"
    te_url = f"{RYU_REST_BASE}/telemetry"

    combined = {
        "algorithm": "round_robin",
        "preferred_path": "path_a",
        "backends": [],
        "total_requests": {},
        "active_connections": {},
        "link_stats": {}
    }

    try:
        with urllib.request.urlopen(stats_url, timeout=2) as resp:
            stats = json.loads(resp.read().decode())
            combined.update(stats)
    except Exception:
        pass

    try:
        with urllib.request.urlopen(te_url, timeout=2) as resp:
            te_data = json.loads(resp.read().decode())
            combined["link_stats"] = te_data.get("link_utilization", {})
    except Exception:
        pass

    return jsonify(combined)

@app.route("/api/set-algo", methods=["POST"])
def set_algo():
    payload = request.get_json()
    url = f"{RYU_REST_BASE}/algorithm"
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return jsonify(json.loads(resp.read().decode())), resp.status
    except urllib.error.HTTPError as he:
        try:
            return jsonify(json.loads(he.read().decode())), he.code
        except Exception:
            return jsonify({"status": "error", "message": str(he)}), he.code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/set-path", methods=["POST"])
def set_path():
    payload = request.get_json()
    url = f"{RYU_REST_BASE}/traffic-engineer/path"
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return jsonify(json.loads(resp.read().decode())), resp.status
    except urllib.error.HTTPError as he:
        try:
            return jsonify(json.loads(he.read().decode())), he.code
        except Exception:
            return jsonify({"status": "error", "message": str(he)}), he.code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8081))
    print(f"[*] Starting SDN Live Web Dashboard on http://0.0.0.0:{port}...")
    app.run(host="0.0.0.0", port=port, threaded=True)
