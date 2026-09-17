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

        # Number of iterations per algorithm for statistical validity
        BENCHMARK_ITERATIONS = 3

        h1 = net.get('h1')

        for algo_key, algo_name in algorithms:
            print(f"\n>>> Running Benchmark: {algo_name} ({BENCHMARK_ITERATIONS} iterations) <<<")
            set_controller_algorithm(algo_key)
            time.sleep(1)

            iteration_results = []
            for run_idx in range(1, BENCHMARK_ITERATIONS + 1):
                print(f"\n  [Run {run_idx}/{BENCHMARK_ITERATIONS}] {algo_name}")
                out_file = os.path.join(RESULTS_DIR, f"{algo_key}_run{run_idx}.json")
                # Execute load generator from client host h1 namespace
                cmd = (f"{sys.executable} {PROJECT_ROOT}/benchmark/generate_load.py "
                       f"--target http://10.0.0.100/ --requests 24 --concurrency 4 --delay 0.03 "
                       f"--out {out_file}")
                print(f"  [*] Executing on h1: {cmd}")
                h1_out = h1.cmd(cmd)
                print(h1_out)

                # Load results from written JSON
                if os.path.exists(out_file):
                    with open(out_file, "r") as f:
                        run_data = json.load(f)
                else:
                    run_data = {"distribution": {}, "records": [], "throughput_rps": 0.0, "latency_ms": {"avg": 0.0}}
                iteration_results.append(run_data)

                # Brief pause between iterations to allow flow timeouts to expire
                if run_idx < BENCHMARK_ITERATIONS:
                    time.sleep(2)

            # Aggregate results across iterations (average metrics)
            agg_dist = {}
            agg_rps = 0.0
            agg_lat = 0.0
            all_records = []
            for run_data in iteration_results:
                d = run_data.get("distribution", {})
                for srv, cnt in d.items():
                    agg_dist[srv] = agg_dist.get(srv, 0) + cnt
                agg_rps += run_data.get("throughput_rps", 0.0)
                agg_lat += run_data.get("latency_ms", {}).get("avg", 0.0)
                all_records.extend(run_data.get("records", []))

            n_runs = len(iteration_results)
            avg_dist = {srv: cnt / n_runs for srv, cnt in agg_dist.items()}
            avg_rps = agg_rps / n_runs
            avg_lat = agg_lat / n_runs

            # Compute latency percentiles across all aggregated records
            all_lats = [r["latency_ms"] for r in all_records if r.get("success", False)]
            if all_lats:
                import numpy as np
                lat_stats = {
                    "min": round(float(np.min(all_lats)), 2),
                    "avg": round(float(np.mean(all_lats)), 2),
                    "median": round(float(np.median(all_lats)), 2),
                    "p90": round(float(np.percentile(all_lats, 90)), 2),
                    "p95": round(float(np.percentile(all_lats, 95)), 2),
                    "p99": round(float(np.percentile(all_lats, 99)), 2),
                    "max": round(float(np.max(all_lats)), 2),
                }
            else:
                lat_stats = {"avg": round(avg_lat, 2)}

            # Compute Jain's Fairness Index from aggregated distribution
            counts = [agg_dist.get(s, 0) for s in ["srv1", "srv2", "srv3", "srv4"]]
            if algo_key == "weighted":
                jfi = calculate_weighted_fairness(agg_dist, weights)
            else:
                jfi = calculate_jains_fairness(counts)

            # Build aggregated result with averaged metrics
            agg_results = {
                "distribution": agg_dist,
                "avg_distribution_per_run": avg_dist,
                "throughput_rps": round(avg_rps, 2),
                "latency_ms": lat_stats,
                "jains_fairness": jfi,
                "iterations": BENCHMARK_ITERATIONS,
                "records": all_records
            }

            # Save aggregated result as the canonical per-algorithm file
            canonical_file = os.path.join(RESULTS_DIR, f"{algo_key}.json")
            with open(canonical_file, "w") as f:
                json.dump(agg_results, f, indent=2)

            summary_metrics[algo_key] = agg_results
            print(f"  [*] Averaged Jain's Fairness Index ({algo_name}, {BENCHMARK_ITERATIONS} runs): {jfi:.4f}")

        # Save summary JSON
        with open(SUMMARY_JSON_PATH, "w") as f:
            json.dump(summary_metrics, f, indent=2)
        print(f"\n[+] Summary benchmark metrics saved to: {SUMMARY_JSON_PATH}")

        # Generate evaluation figures
        print("[*] Generating publication-quality evaluation figures...")
        generate_all_plots(SUMMARY_JSON_PATH)

        # Print comparative summary table
        print("\n===================================================================================================")
        print(f"{'Algorithm':<20} | {'Throughput (rps)':<16} | {'Avg (ms)':<10} | {'P50 (ms)':<10} | {'P95 (ms)':<10} | {'P99 (ms)':<10} | {'JFI':<8}")
        print("---------------------+------------------+------------+------------+------------+------------+---------")
        for algo_key, algo_name in algorithms:
            m = summary_metrics[algo_key]
            rps = m["throughput_rps"]
            l = m["latency_ms"]
            jfi = m["jains_fairness"]
            print(f"{algo_name:<20} | {rps:<16.2f} | {l.get('avg', 0):<10.2f} | {l.get('median', 0):<10.2f} | {l.get('p95', 0):<10.2f} | {l.get('p99', 0):<10.2f} | {jfi:<8.4f}")
        print("===================================================================================================\n")
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
