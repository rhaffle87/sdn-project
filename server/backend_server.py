#!/usr/bin/env python3
"""
Backend Application Server (Flask Microservice)
Emulates an HTTP service running on a backend host behind the SDN Load Balancer.
Returns host identity and request count for distribution verification.
"""

import argparse
import logging
import socket
import time
from flask import Flask, jsonify, request

# Suppress verbose Flask / Werkzeug access logs for high-throughput testing
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app = Flask(__name__)

# State tracking
STATE = {
    "server_id": "srv_unknown",
    "request_count": 0,
    "start_time": time.time(),
    "healthy": True
}

def get_local_ip():
    """Retrieve primary IPv4 address of the local host interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

@app.route("/", methods=["GET", "POST"])
@app.route("/info", methods=["GET"])
def index():
    """Main application endpoint returning identity and counter."""
    STATE["request_count"] += 1
    return jsonify({
        "status": "success",
        "server_id": STATE["server_id"],
        "host_ip": get_local_ip(),
        "client_ip": request.remote_addr,
        "request_count": STATE["request_count"],
        "uptime_seconds": round(time.time() - STATE["start_time"], 2),
        "timestamp": time.time(),
        "message": f"Response from SDN backend: {STATE['server_id']}"
    }), 200

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint used by Ryu controller active health checker."""
    if STATE["healthy"]:
        return jsonify({
            "status": "UP",
            "server_id": STATE["server_id"],
            "request_count": STATE["request_count"]
        }), 200
    else:
        return jsonify({
            "status": "DOWN",
            "server_id": STATE["server_id"]
        }), 503

@app.route("/health/toggle", methods=["POST"])
def toggle_health():
    """Administrative endpoint to set or toggle health state (useful for failover tests)."""
    payload = request.get_json(silent=True) or {}
    if "healthy" in payload:
        STATE["healthy"] = bool(payload["healthy"])
    else:
        STATE["healthy"] = not STATE["healthy"]
    return jsonify({
        "status": "UP" if STATE["healthy"] else "DOWN",
        "server_id": STATE["server_id"]
    }), 200

@app.route("/delay", methods=["GET"])
def simulate_delay():
    """Simulate variable server processing latency."""
    delay = float(request.args.get("seconds", 0.05))
    time.sleep(delay)
    STATE["request_count"] += 1
    return jsonify({
        "server_id": STATE["server_id"],
        "simulated_delay": delay,
        "request_count": STATE["request_count"]
    }), 200

def main():
    parser = argparse.ArgumentParser(description="SDN Load Balancer Backend Microservice")
    parser.add_argument("--id", type=str, default="srv1", help="Unique server identifier")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Binding IP address")
    parser.add_argument("--port", type=int, default=80, help="Listening TCP port")
    args = parser.parse_args()

    STATE["server_id"] = args.id
    print(f"[*] Backend server '{args.id}' starting on {args.host}:{args.port}...")
    app.run(host=args.host, port=args.port, threaded=True)

if __name__ == "__main__":
    main()
