#!/usr/bin/env python3
"""
HTTP Load Generator & Benchmarker
Generates concurrent HTTP traffic to the Virtual IP (VIP) to benchmark
throughput, latency percentiles, and load distribution across backends.
"""

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.request
import numpy as np

def send_single_request(target_url, timeout_sec=3.0):
    """Send a single HTTP GET request and record latency and response data."""
    start_time = time.perf_counter()
    res = {
        "success": False,
        "latency_ms": 0.0,
        "server_id": "unknown",
        "status_code": 0,
        "error": None
    }
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "SDN-LoadBench/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            latency = (time.perf_counter() - start_time) * 1000.0
            res["latency_ms"] = round(latency, 2)
            res["status_code"] = response.status
            if response.status == 200:
                body = json.loads(response.read().decode())
                res["success"] = True
                res["server_id"] = body.get("server_id", "unknown")
    except Exception as e:
        res["latency_ms"] = round((time.perf_counter() - start_time) * 1000.0, 2)
        res["error"] = str(e)
    return res

def run_benchmark(target_url, total_requests, concurrency, delay_sec=0.0):
    """Execute concurrent load generation against the target URL."""
    print(f"[*] Commencing Load Test -> Target: {target_url}")
    print(f"    Total Requests: {total_requests} | Concurrency: {concurrency} | Inter-request Delay: {delay_sec}s")

    records = []
    start_wall = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for _ in range(total_requests):
            futures.append(executor.submit(send_single_request, target_url))
            if delay_sec > 0:
                time.sleep(delay_sec)

        for future in concurrent.futures.as_completed(futures):
            records.append(future.result())

    total_duration = time.time() - start_wall
    return analyze_results(records, total_duration)

def analyze_results(records, total_duration):
    """Compute summary statistical metrics from test records."""
    successful = [r for r in records if r["success"]]
    failed = [r for r in records if not r["success"]]

    latencies = [r["latency_ms"] for r in successful] if successful else [0.0]
    throughput_rps = round(len(successful) / max(0.001, total_duration), 2)

    # Server distribution count
    distribution = {}
    for r in successful:
        srv = r["server_id"]
        distribution[srv] = distribution.get(srv, 0) + 1

    summary = {
        "total_requests": len(records),
        "successful_requests": len(successful),
        "failed_requests": len(failed),
        "success_rate_pct": round((len(successful) / max(1, len(records))) * 100.0, 2),
        "total_duration_sec": round(total_duration, 2),
        "throughput_rps": throughput_rps,
        "latency_ms": {
            "min": round(float(np.min(latencies)), 2),
            "avg": round(float(np.mean(latencies)), 2),
            "median": round(float(np.median(latencies)), 2),
            "p95": round(float(np.percentile(latencies, 95)), 2),
            "p99": round(float(np.percentile(latencies, 99)), 2),
            "max": round(float(np.max(latencies)), 2)
        },
        "distribution": distribution,
        "records": records
    }

    print("\n=======================================================")
    print("                 BENCHMARK RESULTS                     ")
    print("=======================================================")
    print(f"  Duration:         {summary['total_duration_sec']}s")
    print(f"  Throughput:       {summary['throughput_rps']} req/s")
    print(f"  Success Rate:     {summary['successful_requests']}/{summary['total_requests']} ({summary['success_rate_pct']}%)")
    print(f"  Avg Latency:      {summary['latency_ms']['avg']} ms")
    print(f"  Median (p50):     {summary['latency_ms']['median']} ms")
    print(f"  95th Percentile:  {summary['latency_ms']['p95']} ms")
    print(f"  99th Percentile:  {summary['latency_ms']['p99']} ms")
    print("  Load Distribution per Backend:")
    for srv, count in sorted(distribution.items()):
        pct = (count / max(1, len(successful))) * 100.0
        print(f"    - {srv:10s}: {count:4d} requests ({pct:5.1f}%)")
    print("=======================================================\n")

    return summary

def main():
    parser = argparse.ArgumentParser(description="SDN Load Balancer HTTP Load Generator")
    parser.add_argument("--target", type=str, default="http://10.0.0.100/", help="Target URL (VIP)")
    parser.add_argument("--requests", type=int, default=50, help="Total number of requests")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent client threads")
    parser.add_argument("--delay", type=float, default=0.02, help="Inter-request dispatch delay in seconds")
    parser.add_argument("--out", type=str, default=None, help="File path to save JSON metrics")
    args = parser.parse_args()

    results = run_benchmark(args.target, args.requests, args.concurrency, args.delay)

    if args.out:
        out_dir = os.path.dirname(args.out)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)
        print(f"[*] Detailed metrics written to: {args.out}")

if __name__ == "__main__":
    main()
