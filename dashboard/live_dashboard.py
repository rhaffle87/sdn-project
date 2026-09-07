#!/usr/bin/env python3
"""
Live Web Telemetry & Management Dashboard
Provides real-time visualization of backend load distribution, link bandwidth utilization,
health states, interactive traffic generation, server crash simulation, and telemetry event streaming.
"""

import collections
import json
import logging
import os
import subprocess
import time
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
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
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
            font-size: 1.05rem;
            color: var(--text-bright);
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
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
        button.active {
            background: var(--primary);
            color: #0d1117;
            font-weight: 700;
            border-color: var(--primary);
            box-shadow: 0 0 10px rgba(88, 166, 255, 0.4);
        }
        button.btn-accent {
            background: #1f6feb;
            color: #ffffff;
            border-color: #388bfd;
            font-weight: 600;
        }
        button.btn-accent:hover { background: #388bfd; }
        button.btn-danger {
            background: #21262d;
            border-color: #da3633;
            color: #f85149;
        }
        button.btn-danger:hover { background: #da3633; color: #fff; }
        button.btn-success {
            background: #21262d;
            border-color: #238636;
            color: #3fb950;
        }
        button.btn-success:hover { background: #238636; color: #fff; }
        button.pulsing {
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(63, 185, 80, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(63, 185, 80, 0); }
            100% { box-shadow: 0 0 0 0 rgba(63, 185, 80, 0); }
        }
        .server-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 0;
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
            font-size: 0.82rem;
            color: #8b949e;
            height: 120px;
            overflow-y: auto;
            line-height: 1.5;
        }
        .log-entry { margin-bottom: 3px; }
        .log-time { color: #6e7681; margin-right: 6px; }
        .log-tag-lb { color: var(--primary); font-weight: bold; }
        .log-tag-te { color: var(--purple); font-weight: bold; }
        .log-tag-traffic { color: var(--warning); font-weight: bold; }
        .log-tag-health { color: var(--danger); font-weight: bold; }
        .log-tag-ok { color: var(--success); font-weight: bold; }
        .path-active-tag {
            font-size: 0.75rem;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
        }
        .tag-active { background: #23863633; color: var(--success); border: 1px solid var(--success); }
        .tag-standby { background: #30363d; color: #8b949e; }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>SDN Load Balancer &amp; Traffic Engineering Telemetry</h1>
            <p style="font-size: 0.85rem; color: #8b949e; margin-top: 4px;">OpenFlow 1.3 Control Plane &amp; Data Center Traffic Optimization</p>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
            <span class="badge" id="active-algo-badge">Algorithm: Round-Robin</span>
            <span class="badge" style="border-color: var(--purple); color: var(--purple);" id="active-path-badge">Active Path: Path A (Upper)</span>
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
                <p style="font-size: 0.85rem; color: #8b949e;">Transit Path Selection (Traffic Engineering):</p>
                <div class="btn-group">
                    <button id="btn-path-auto" onclick="setPath('auto')" class="active">Auto (Adaptive TE)</button>
                    <button id="btn-path-a" onclick="setPath('path_a')">Force Path A (Upper)</button>
                    <button id="btn-path-b" onclick="setPath('path_b')">Force Path B (Lower)</button>
                </div>
            </div>
        </div>

        <!-- 2. Traffic Generator & Simulator -->
        <div class="card">
            <h2>Client Traffic Generator</h2>
            <p style="font-size: 0.85rem; color: #8b949e;">Dispatch HTTP requests from Mininet client <code>h1</code> targeting VIP <code>10.0.0.100:80</code>:</p>
            <div class="btn-group">
                <button class="btn-accent" onclick="sendTraffic(1)">⚡ Send 1 Request</button>
                <button class="btn-accent" onclick="sendTraffic(8)">🚀 Send 8 Requests (Burst)</button>
                <button id="btn-auto-traffic" onclick="toggleContinuousTraffic()">🌊 Continuous Traffic: OFF</button>
            </div>
            <div style="margin-top: 16px;">
                <div class="metric-row">
                    <span style="color: #8b949e;">Generator Status:</span>
                    <span id="gen-status" style="color: var(--text-bright); font-weight: 500;">Idle</span>
                </div>
                <div class="metric-row" style="margin-top: 4px;">
                    <span style="color: #8b949e;">Last Dispatch Latency:</span>
                    <span id="gen-latency" style="color: var(--primary);">-- ms</span>
                </div>
            </div>
        </div>

        <!-- 3. Transit Link Telemetry -->
        <div class="card">
            <h2>Transit Link Telemetry (10 Mbps Links)</h2>
            <div style="margin-bottom: 14px;">
                <div class="metric-row">
                    <span>
                        Path A (s1 &harr; s2 &harr; s4)
                        <span id="path-a-tag" class="path-active-tag tag-active">ACTIVE</span>
                    </span>
                    <span id="path-a-text" style="font-weight: 600;">0.0 kbps (0.0%)</span>
                </div>
                <div class="bar-container">
                    <div class="bar-fill bar-primary" id="path-a-bar" style="width: 0%;"></div>
                </div>
                <div class="metric-row" style="font-size: 0.78rem; color: #8b949e;">
                    <span>Cumulative Data:</span>
                    <span id="path-a-cum">0 KB</span>
                </div>
            </div>
            <div>
                <div class="metric-row">
                    <span>
                        Path B (s1 &harr; s3 &harr; s4)
                        <span id="path-b-tag" class="path-active-tag tag-standby">STANDBY</span>
                    </span>
                    <span id="path-b-text" style="font-weight: 600;">0.0 kbps (0.0%)</span>
                </div>
                <div class="bar-container">
                    <div class="bar-fill bar-primary" id="path-b-bar" style="width: 0%;"></div>
                </div>
                <div class="metric-row" style="font-size: 0.78rem; color: #8b949e;">
                    <span>Cumulative Data:</span>
                    <span id="path-b-cum">0 KB</span>
                </div>
            </div>
            <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid #21262d;">
                <div class="metric-row">
                    <span style="color: #8b949e;">Adaptive TE Status:</span>
                    <span id="te-status" style="color: var(--success); font-weight: 600;">Nominal (&lt; 80%)</span>
                </div>
            </div>
        </div>

        <!-- 4. Telemetry Events Log -->
        <div class="card" style="grid-column: 1 / -1;">
            <h2>
                <span>Telemetry Events &amp; Audit Log</span>
                <button onclick="clearLogs()" style="padding: 4px 10px; font-size: 0.75rem;">Clear Log</button>
            </h2>
            <div class="log-box" id="event-log"></div>
        </div>
    </div>

    <!-- 5. Backend Server Pool -->
    <div class="card">
        <h2>
            <span>Backend Application Server Pool (Virtual IP: 10.0.0.100:80)</span>
            <span style="font-size: 0.85rem; color: #8b949e; font-weight: normal;">Simulate server crash or recovery by clicking action buttons</span>
        </h2>
        <div id="backend-list">
            Loading backend statuses...
        </div>
    </div>

    <script>
        let previousTotalRequests = {};
        let continuousTrafficTimer = null;
        let isGenerating = false;

        function getTimestamp() {
            const now = new Date();
            return now.toTimeString().split(' ')[0];
        }

        function logEvent(tag, tagClass, message) {
            const box = document.getElementById('event-log');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.innerHTML = `<span class="log-time">[${getTimestamp()}]</span> <span class="${tagClass}">[${tag}]</span> ${message}`;
            box.appendChild(entry);
            box.scrollTop = box.scrollHeight;
        }

        function clearLogs() {
            document.getElementById('event-log').innerHTML = '';
            logEvent('System', 'log-tag-ok', 'Event log cleared.');
        }

        // Initial system event
        logEvent('System', 'log-tag-ok', 'Telemetry monitoring initialized and streaming.');

        async function fetchTelemetry() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();

                // 1. Update Algorithm & Path Badges
                const algoNames = {
                    "round_robin": "Round-Robin",
                    "least_connections": "Least-Connections",
                    "weighted": "Weighted (1:2:1:2)"
                };
                document.getElementById('active-algo-badge').innerText = 'Algorithm: ' + (algoNames[data.algorithm] || data.algorithm);
                
                const manualLock = data.manual_override || (data.te_status && data.te_status.manual_override);
                const pathSuffix = manualLock ? ' [Locked]' : ' [Adaptive Auto]';
                const pathName = data.preferred_path === 'path_a' ? 'Path A (Upper)' : 'Path B (Lower)';
                document.getElementById('active-path-badge').innerText = `Active Path: ${pathName}${pathSuffix}`;

                // 2. Update active buttons
                document.getElementById('btn-rr').className = data.algorithm === 'round_robin' ? 'active' : '';
                document.getElementById('btn-lc').className = data.algorithm === 'least_connections' ? 'active' : '';
                document.getElementById('btn-w').className = data.algorithm === 'weighted' ? 'active' : '';

                document.getElementById('btn-path-auto').className = !manualLock ? 'active' : '';
                document.getElementById('btn-path-a').className = manualLock === 'path_a' ? 'active' : '';
                document.getElementById('btn-path-b').className = manualLock === 'path_b' ? 'active' : '';

                // 3. Update Path Badges
                if (data.preferred_path === 'path_a') {
                    document.getElementById('path-a-tag').className = 'path-active-tag tag-active';
                    document.getElementById('path-a-tag').innerText = 'ACTIVE';
                    document.getElementById('path-b-tag').className = 'path-active-tag tag-standby';
                    document.getElementById('path-b-tag').innerText = 'STANDBY';
                } else {
                    document.getElementById('path-a-tag').className = 'path-active-tag tag-standby';
                    document.getElementById('path-a-tag').innerText = 'STANDBY';
                    document.getElementById('path-b-tag').className = 'path-active-tag tag-active';
                    document.getElementById('path-b-tag').innerText = 'ACTIVE';
                }

                // 4. Update Link Telemetry
                const linkStats = data.link_stats || {};
                const pa = linkStats.path_a || { bps: 0, ratio: 0, tx_bytes: 0 };
                const pb = linkStats.path_b || { bps: 0, ratio: 0, tx_bytes: 0 };

                const paPct = Math.min(100, (pa.ratio * 100)).toFixed(1);
                const pbPct = Math.min(100, (pb.ratio * 100)).toFixed(1);

                // Format rate nicely (bps, kbps, Mbps)
                function formatRate(bps) {
                    if (bps >= 1000000) return (bps / 1000000).toFixed(2) + ' Mbps';
                    if (bps >= 1000) return (bps / 1000).toFixed(1) + ' kbps';
                    return bps.toFixed(0) + ' bps';
                }

                function formatBytes(bytes) {
                    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
                    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
                    return bytes + ' B';
                }

                document.getElementById('path-a-text').innerText = `${formatRate(pa.bps)} (${paPct}%)`;
                document.getElementById('path-a-bar').style.width = Math.max(paPct > 0 ? 3 : 0, paPct) + '%';
                document.getElementById('path-a-bar').className = 'bar-fill ' + (paPct > 80 ? 'bar-danger' : paPct > 50 ? 'bar-warning' : 'bar-primary');
                document.getElementById('path-a-cum').innerText = formatBytes(pa.tx_bytes || 0);

                document.getElementById('path-b-text').innerText = `${formatRate(pb.bps)} (${pbPct}%)`;
                document.getElementById('path-b-bar').style.width = Math.max(pbPct > 0 ? 3 : 0, pbPct) + '%';
                document.getElementById('path-b-bar').className = 'bar-fill ' + (pbPct > 80 ? 'bar-danger' : pbPct > 50 ? 'bar-warning' : 'bar-primary');
                document.getElementById('path-b-cum').innerText = formatBytes(pb.tx_bytes || 0);

                const maxUtil = Math.max(pa.ratio, pb.ratio);
                const teEl = document.getElementById('te-status');
                if (maxUtil >= 0.80) {
                    teEl.innerText = `Saturated! (${(maxUtil*100).toFixed(1)}%) - Alternate Path Rerouted`;
                    teEl.style.color = 'var(--danger)';
                } else if (maxUtil >= 0.50) {
                    teEl.innerText = `Elevated (${(maxUtil*100).toFixed(1)}%)`;
                    teEl.style.color = 'var(--warning)';
                } else {
                    teEl.innerText = 'Nominal (< 80% Threshold)';
                    teEl.style.color = 'var(--success)';
                }

                // 5. Update Backend Server List & Detect traffic deltas
                const backends = data.backends || [];
                const reqCounts = data.total_requests || {};
                const activeConns = data.active_connections || {};

                // Calculate total across all backends for percentage bars
                let grandTotal = 0;
                backends.forEach(b => { grandTotal += (reqCounts[b.id] || 0); });

                let html = '';
                backends.forEach(b => {
                    const statusClass = b.healthy ? 'status-up' : 'status-down';
                    const statusText = b.healthy ? 'ONLINE' : 'OFFLINE';
                    const totalReq = reqCounts[b.id] || 0;
                    const conns = activeConns[b.id] || 0;
                    const sharePct = grandTotal > 0 ? ((totalReq / grandTotal) * 100).toFixed(1) : 0;

                    // Detect delta for logging
                    const prevReq = previousTotalRequests[b.id] || 0;
                    if (totalReq > prevReq && Object.keys(previousTotalRequests).length > 0) {
                        const delta = totalReq - prevReq;
                        logEvent('LoadBalancer', 'log-tag-lb', `${b.id} served +${delta} new client requests (Total: ${totalReq})`);
                    }

                    // Dynamic contextual weight badge
                    let weightBadge = '';
                    if (data.algorithm === 'weighted') {
                        weightBadge = `<span style="background: rgba(88, 166, 255, 0.15); color: #58a6ff; border: 1px solid rgba(88, 166, 255, 0.3); padding: 2px 7px; border-radius: 10px; font-size: 0.72rem; margin-left: 8px; font-weight: 600;">Weight: ${b.weight} (Active: 1:2:1:2)</span>`;
                    } else if (data.algorithm === 'round_robin') {
                        weightBadge = `<span style="background: rgba(139, 148, 158, 0.1); color: #8b949e; border: 1px solid #30363d; padding: 2px 7px; border-radius: 10px; font-size: 0.72rem; margin-left: 8px;">Weight: ${b.weight} (Inactive &bull; Equal 1:1:1:1)</span>`;
                    } else {
                        weightBadge = `<span style="background: rgba(139, 148, 158, 0.1); color: #8b949e; border: 1px solid #30363d; padding: 2px 7px; border-radius: 10px; font-size: 0.72rem; margin-left: 8px;">Weight: ${b.weight} (Inactive &bull; Min Connections)</span>`;
                    }

                    // Toggle button
                    const toggleBtn = b.healthy 
                        ? `<button class="btn-danger" style="padding: 4px 10px; font-size: 0.78rem;" onclick="toggleServer('${b.id}', false)">Simulate Crash</button>`
                        : `<button class="btn-success" style="padding: 4px 10px; font-size: 0.78rem;" onclick="toggleServer('${b.id}', true)">Recover Server</button>`;

                    html += `
                    <div class="server-item">
                        <div style="flex: 1;">
                            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 4px;">
                                <span class="status-dot ${statusClass}"></span>
                                <strong style="color: var(--text-bright); font-size: 0.95rem;">${b.id}</strong>
                                <span style="color: #8b949e; font-size: 0.85rem; margin-left: 6px;">${b.ip}:${b.port}</span>
                                ${weightBadge}
                            </div>
                            <div class="bar-container" style="height: 6px; width: 85%; margin-top: 6px;">
                                <div class="bar-fill bar-primary" style="width: ${sharePct}%;"></div>
                            </div>
                        </div>
                        <div style="display: flex; gap: 20px; align-items: center; font-size: 0.85rem;">
                            <span>Active Conns: <strong>${conns}</strong></span>
                            <span>Total Served: <strong>${totalReq}</strong> <small style="color: #8b949e;">(${sharePct}%)</small></span>
                            <span style="font-weight: 600; color: ${b.healthy ? 'var(--success)' : 'var(--danger)'};">${statusText}</span>
                            ${toggleBtn}
                        </div>
                    </div>`;
                });
                document.getElementById('backend-list').innerHTML = html;
                previousTotalRequests = Object.assign({}, reqCounts);

            } catch (err) {
                console.error("Failed to fetch telemetry:", err);
            }
        }

        async function setAlgorithm(algo) {
            const algoNames = {
                "round_robin": "Round-Robin",
                "least_connections": "Least-Connections",
                "weighted": "Weighted (1:2:1:2)"
            };
            try {
                const res = await fetch('/api/set-algo', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ algorithm: algo })
                });
                if (res.ok) {
                    logEvent('LB Policy', 'log-tag-lb', `Algorithm policy changed to: ${algoNames[algo] || algo}`);
                } else {
                    logEvent('Error', 'log-tag-health', `Failed to change algorithm: HTTP ${res.status}`);
                }
            } catch (e) {
                logEvent('Error', 'log-tag-health', `Algorithm switch error: ${e.message}`);
            }
            fetchTelemetry();
        }

        async function setPath(path) {
            const pathNames = { 
                "auto": "Auto (Adaptive Dynamic TE - Congestion Rerouting)",
                "path_a": "Path A (Upper) [Manual Lock]", 
                "path_b": "Path B (Lower) [Manual Lock]" 
            };
            try {
                const res = await fetch('/api/set-path', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: path })
                });
                if (res.ok) {
                    logEvent('Traffic Engineering', 'log-tag-te', `Transit path mode set to: ${pathNames[path] || path}`);
                } else {
                    logEvent('Error', 'log-tag-health', `Failed to set path: HTTP ${res.status}`);
                }
            } catch (e) {
                logEvent('Error', 'log-tag-health', `Path switch error: ${e.message}`);
            }
            fetchTelemetry();
        }

        async function sendTraffic(count) {
            if (isGenerating) return;
            isGenerating = true;
            document.getElementById('gen-status').innerText = `Sending ${count} requests to VIP...`;
            document.getElementById('gen-status').style.color = 'var(--warning)';

            const start = performance.now();
            try {
                const res = await fetch('/api/generate-traffic', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ count: count })
                });
                const elapsed = (performance.now() - start).toFixed(1);
                document.getElementById('gen-latency').innerText = `${elapsed} ms`;

                const data = await res.json();
                if (data.status === 'success') {
                    document.getElementById('gen-status').innerText = `Success (${count} reqs sent)`;
                    document.getElementById('gen-status').style.color = 'var(--success)';
                    
                    const servedSummary = data.breakdown 
                        ? Object.entries(data.breakdown).map(([k, v]) => `${k}: ${v}`).join(', ')
                        : `${count} requests distributed`;
                    logEvent('Traffic Gen', 'log-tag-traffic', `Dispatched ${count} client requests to VIP (10.0.0.100). Served: [${servedSummary}] in ${elapsed}ms`);
                } else {
                    document.getElementById('gen-status').innerText = 'Error';
                    document.getElementById('gen-status').style.color = 'var(--danger)';
                    logEvent('Traffic Gen', 'log-tag-health', `Traffic generation failed: ${data.message}`);
                }
            } catch (e) {
                document.getElementById('gen-status').innerText = 'Failed';
                document.getElementById('gen-status').style.color = 'var(--danger)';
                logEvent('Traffic Gen', 'log-tag-health', `Network error: ${e.message}`);
            } finally {
                isGenerating = false;
                fetchTelemetry();
            }
        }

        function toggleContinuousTraffic() {
            const btn = document.getElementById('btn-auto-traffic');
            if (continuousTrafficTimer) {
                clearInterval(continuousTrafficTimer);
                continuousTrafficTimer = null;
                btn.className = '';
                btn.innerText = '🌊 Continuous Traffic: OFF';
                logEvent('Traffic Gen', 'log-tag-ok', 'Continuous background traffic generator stopped.');
            } else {
                btn.className = 'btn-success pulsing';
                btn.innerText = '⏸ Continuous Traffic: ON (2 req/s)';
                logEvent('Traffic Gen', 'log-tag-traffic', 'Continuous background traffic generator started (2 requests every 1.5s).');
                // Run immediately then every 1.5s
                sendTraffic(2);
                continuousTrafficTimer = setInterval(() => {
                    sendTraffic(2);
                }, 1500);
            }
        }

        async function toggleServer(backendId, healthyState) {
            const action = healthyState ? 'recovering' : 'crashing';
            logEvent('Health Prober', healthyState ? 'log-tag-ok' : 'log-tag-health', `Simulating ${action} on ${backendId}...`);
            try {
                const res = await fetch('/api/toggle-server', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ backend_id: backendId, healthy: healthyState })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    logEvent('Health Prober', healthyState ? 'log-tag-ok' : 'log-tag-health', 
                             `${backendId} is now ${healthyState ? 'ONLINE (re-added to pool)' : 'OFFLINE (excluded from load balancer)'}!`);
                } else {
                    logEvent('Error', 'log-tag-health', `Failed to toggle ${backendId}: ${data.message}`);
                }
            } catch (e) {
                logEvent('Error', 'log-tag-health', `Server toggle error: ${e.message}`);
            }
            fetchTelemetry();
        }

        // Live polling every 2 seconds
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
            te_status = te_data.get("traffic_engineering", {})
            if "preferred_path" in te_status:
                combined["preferred_path"] = te_status["preferred_path"]
            if "manual_override" in te_status:
                combined["manual_override"] = te_status["manual_override"]
            combined["te_status"] = te_status
    except Exception:
        pass

    return jsonify(combined)

@app.route("/api/set-algo", methods=["POST"])
def set_algo():
    payload = request.get_json(silent=True) or {}
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
    payload = request.get_json(silent=True) or {}
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

@app.route("/api/generate-traffic", methods=["POST"])
def generate_traffic():
    """Dispatch client requests from Mininet client h1 to VIP 10.0.0.100."""
    payload = request.get_json(silent=True) or {}
    count = int(payload.get("count", 4))
    count = max(1, min(50, count))

    try:
        # 1. Locate h1 Mininet PID
        out = subprocess.check_output(["pgrep", "-f", "mininet:h1"]).decode().strip().split()
        if not out:
            return jsonify({"status": "error", "message": "Mininet host h1 is not running"}), 500
        h1_pid = out[0]

        # 2. Run Python requests script inside h1 network namespace
        py_snippet = (
            "import urllib.request, json\n"
            "results = []\n"
            f"for _ in range({count}):\n"
            "    try:\n"
            "        with urllib.request.urlopen('http://10.0.0.100/', timeout=2) as r:\n"
            "            d = json.loads(r.read().decode())\n"
            "            results.append(d.get('server_id', 'unknown'))\n"
            "    except Exception:\n"
            "        results.append('error')\n"
            "print(json.dumps(results))\n"
        )
        cmd = ["sudo", "mnexec", "-a", h1_pid, "python3", "-c", py_snippet]
        raw_out = subprocess.check_output(cmd, timeout=12).decode().strip()
        
        servers = json.loads(raw_out)
        breakdown = collections.Counter(servers)
        return jsonify({
            "status": "success",
            "count": count,
            "servers": servers,
            "breakdown": dict(breakdown)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/toggle-server", methods=["POST"])
def toggle_server():
    """Simulate server crash or recovery by forwarding to Ryu health API."""
    payload = request.get_json(silent=True) or {}
    b_id = payload.get("backend_id")
    healthy = payload.get("healthy")

    if not b_id or healthy is None:
        return jsonify({"status": "error", "message": "Missing backend_id or healthy state"}), 400

    url = f"{RYU_REST_BASE}/backend/health"
    data = json.dumps({"backend_id": b_id, "healthy": bool(healthy)}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
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
