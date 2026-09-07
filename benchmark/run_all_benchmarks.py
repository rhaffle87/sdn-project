#!/usr/bin/env python3
"""
Full Benchmark Suite Orchestrator
Executes systematic evaluations of Round-Robin, Least-Connections, and Weighted algorithms.
Calculates Jain's Fairness Index and automatically triggers generation of scientific figures.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel
from topology.lb_topology import DiamondLBTopo, start_backend_servers
from benchmark.generate_load import run_benchmark
from benchmark.measure_fairness import calculate_jains_fairness, calculate_weighted_fairness
from dashboard.plot_results import generate_all_plots

RESULTS_DIR = os.path.join(PROJECT_ROOT, "benchmark", "results")
SUMMARY_JSON_PATH = os.path.join(RESULTS_DIR, "summary_metrics.json")

def set_controller_algorithm(algo_name):
    """Set active load balancing algorithm on Ryu controller."""
    url = "http://127.0.0.1:8080/api/algorithm"
    data = json.dumps({"algorithm": algo_name}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[WARN] Could not set algorithm via REST: {e}")
        return False

def run_all_benchmarks():
    setLogLevel('info')
    print("\n=======================================================")
    print("   SDN LOAD BALANCER COMPREHENSIVE BENCHMARK SUITE     ")
    print("=======================================================\n")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    subprocess.run(["sudo", "pkill", "-f", "backend_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    topo = DiamondLBTopo()
    net = Mininet(topo=topo, switch=OVSSwitch, controller=None, autoSetMacs=False, autoStaticArp=False)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    summary_metrics = {}

    try:
        net.start()
        start_backend_servers(net, PROJECT_ROOT)
        time.sleep(3)

        algorithms = [
            ("round_robin", "Round-Robin"),
            ("least_connections", "Least-Connections"),
            ("weighted", "Weighted (1:2:1:2)")
        ]

        # Weights dictionary for weighted fairness calculation
        weights = {"srv1": 1, "srv2": 2, "srv3": 1, "srv4": 2}

        h1 = net.get('h1')

        for algo_key, algo_name in algorithms:
            print(f"\n>>> Running Benchmark: {algo_name} <<<")
            set_controller_algorithm(algo_key)
            time.sleep(1)

            out_file = os.path.join(RESULTS_DIR, f"{algo_key}.json")
            # Execute load generator from client host h1 namespace
            cmd = (f"/home/rafli_alif/sdn-venv/bin/python3 {PROJECT_ROOT}/benchmark/generate_load.py "
                   f"--target http://10.0.0.100/ --requests 24 --concurrency 4 --delay 0.03 "
                   f"--out {out_file}")
            print(f"[*] Executing on h1: {cmd}")
            h1_out = h1.cmd(cmd)
            print(h1_out)

            # Load results from written JSON
            if os.path.exists(out_file):
                with open(out_file, "r") as f:
                    results = json.load(f)
            else:
                results = {"distribution": {}, "records": [], "throughput_rps": 0.0, "latency_ms": {"avg": 0.0}}

            # Compute Jain's Fairness Index
            dist = results.get("distribution", {})
            counts = [dist.get(s, 0) for s in ["srv1", "srv2", "srv3", "srv4"]]

            if algo_key == "weighted":
                jfi = calculate_weighted_fairness(dist, weights)
            else:
                jfi = calculate_jains_fairness(counts)

            results["jains_fairness"] = jfi
            summary_metrics[algo_key] = results
            print(f"[*] Computed Jain's Fairness Index ({algo_name}): {jfi:.4f}")

        # Save summary JSON
        with open(SUMMARY_JSON_PATH, "w") as f:
            json.dump(summary_metrics, f, indent=2)
        print(f"\n[+] Summary benchmark metrics saved to: {SUMMARY_JSON_PATH}")

        # Generate evaluation figures
        print("[*] Generating publication-quality evaluation figures...")
        generate_all_plots(SUMMARY_JSON_PATH)

        # Print comparative summary table
        print("\n=========================================================================")
        print(f"{'Algorithm':<20} | {'Throughput (rps)':<16} | {'Avg Latency (ms)':<16} | {'JFI':<8}")
        print("---------------------+------------------+------------------+---------")
        for algo_key, algo_name in algorithms:
            m = summary_metrics[algo_key]
            rps = m["throughput_rps"]
            avg_lat = m["latency_ms"]["avg"]
            jfi = m["jains_fairness"]
            print(f"{algo_name:<20} | {rps:<16.2f} | {avg_lat:<16.2f} | {jfi:<8.4f}")
        print("=========================================================================\n")
        return True

    except Exception as e:
        print(f"[FAIL] Benchmark suite failed with error: {e}")
        return False
    finally:
        subprocess.run(["sudo", "pkill", "-f", "backend_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        net.stop()
        subprocess.run(["sudo", "mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    success = run_all_benchmarks()
    sys.exit(0 if success else 1)
