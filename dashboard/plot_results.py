#!/usr/bin/env python3
"""
Scientific Figure Generator for SDN Load Balancer Capstone
Generates publication-quality charts for documentation, presentations, and final reports:
1. Load distribution across backends (Bar Chart)
2. Cumulative Distribution Function (CDF) of request latencies
3. Jain's Fairness Index comparison
4. System throughput & response time trade-off
"""

import json
import os
import sys
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIGURES_DIR = os.path.join(PROJECT_ROOT, "figures")

# Modern, academic aesthetic style
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.size'] = 11
plt.rcParams['axes.titlesize'] = 13
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 10
plt.rcParams['figure.titlesize'] = 14

COLORS = {
    "round_robin": "#1f77b4",        # Blue
    "least_connections": "#2ca02c",  # Green
    "weighted": "#ff7f0e",           # Orange
    "srv1": "#4c72b0",
    "srv2": "#55a868",
    "srv3": "#c44e52",
    "srv4": "#8172b3"
}

def plot_load_distribution(summary_data, out_path):
    """Generate comparative bar chart of load distribution per backend."""
    servers = ["srv1", "srv2", "srv3", "srv4"]
    algos = ["round_robin", "least_connections", "weighted"]
    algo_labels = ["Round-Robin", "Least-Connections", "Weighted (1:2:1:2)"]

    x = np.arange(len(servers))
    width = 0.25

    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=300)

    for i, algo in enumerate(algos):
        dist = summary_data.get(algo, {}).get("distribution", {})
        counts = [dist.get(s, 0) for s in servers]
        offset = (i - 1) * width
        bars = ax.bar(x + offset, counts, width, label=algo_labels[i], color=COLORS[algo], alpha=0.88, edgecolor='black', linewidth=0.8)
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.annotate(f'{int(height)}',
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3), textcoords="offset points",
                            ha='center', va='bottom', fontsize=9, fontweight='bold')

    ax.set_ylabel('Total Requests Served', fontweight='bold')
    ax.set_xlabel('Backend Server Instances', fontweight='bold')
    ax.set_title('Backend Load Distribution Across Load Balancing Algorithms', pad=15, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s}\n({s.replace('srv', 'Server ')})" for s in servers])
    ax.legend(frameon=True, facecolor='white', framealpha=0.95)
    ax.set_ylim(0, max(15, ax.get_ylim()[1] * 1.15))

    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"[+] Saved load distribution figure: {out_path}")

def plot_latency_cdf(summary_data, out_path):
    """Generate Cumulative Distribution Function (CDF) for request latencies."""
    fig, ax = plt.subplots(figsize=(8.5, 5), dpi=300)

    algos = ["round_robin", "least_connections", "weighted"]
    labels = ["Round-Robin", "Least-Connections", "Weighted"]

    for algo, label in zip(algos, labels):
        records = summary_data.get(algo, {}).get("records", [])
        latencies = [r["latency_ms"] for r in records if r.get("success", False)]
        if latencies:
            sorted_lat = np.sort(latencies)
            cdf = np.arange(1, len(sorted_lat) + 1) / len(sorted_lat)
            ax.plot(sorted_lat, cdf, label=label, color=COLORS[algo], linewidth=2.2)

    ax.set_xlabel('Response Latency (ms)', fontweight='bold')
    ax.set_ylabel('Cumulative Probability (CDF)', fontweight='bold')
    ax.set_title('Empirical Latency CDF Under Concurrent Load', pad=15, fontweight='bold')
    ax.set_ylim(0, 1.05)
    ax.grid(True, linestyle='--', alpha=0.6)
    ax.legend(frameon=True, facecolor='white', framealpha=0.95, loc='lower right')

    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"[+] Saved latency CDF figure: {out_path}")

def plot_fairness_comparison(summary_data, out_path):
    """Generate Jain's Fairness Index comparison bar chart."""
    algos = ["round_robin", "least_connections", "weighted"]
    labels = ["Round-Robin", "Least-Connections", "Weighted\n(Normalized)"]
    jfi_values = []

    for algo in algos:
        val = summary_data.get(algo, {}).get("jains_fairness", 0.0)
        jfi_values.append(val)

    fig, ax = plt.subplots(figsize=(7, 4.8), dpi=300)
    x = np.arange(len(algos))
    bars = ax.bar(x, jfi_values, width=0.45, color=[COLORS[a] for a in algos], alpha=0.9, edgecolor='black', linewidth=0.8)

    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.4f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 4), textcoords="offset points",
                    ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.set_ylabel("Jain's Fairness Index (JFI)", fontweight='bold')
    ax.set_title("Jain's Fairness Index Across Load Balancing Algorithms", pad=15, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.25)
    ax.axhline(1.0, color='red', linestyle=':', linewidth=1.2, label='Ideal Fairness (1.0000)')
    ax.legend(loc='lower right', frameon=True, facecolor='white', framealpha=0.95)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"[+] Saved fairness index comparison: {out_path}")

def plot_throughput_comparison(summary_data, out_path):
    """Generate throughput (requests per second) comparison bar chart."""
    algos = ["round_robin", "least_connections", "weighted"]
    labels = ["Round-Robin", "Least-Connections", "Weighted\n(1:2:1:2)"]
    rps_values = []

    for algo in algos:
        val = summary_data.get(algo, {}).get("throughput_rps", 0.0)
        rps_values.append(val)

    fig, ax = plt.subplots(figsize=(7, 4.8), dpi=300)
    x = np.arange(len(algos))
    bars = ax.bar(x, rps_values, width=0.45, color=[COLORS[a] for a in algos], alpha=0.9, edgecolor='black', linewidth=0.8)

    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.2f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 4), textcoords="offset points",
                    ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.set_ylabel("Throughput (Requests/Second)", fontweight='bold')
    ax.set_title("System Throughput Across Load Balancing Algorithms", pad=15, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(1, max(rps_values) * 1.25) if rps_values else 1)
    ax.grid(axis='y', linestyle='--', alpha=0.5)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"[+] Saved throughput comparison figure: {out_path}")

def generate_all_plots(summary_json_path):
    """Read summary data and generate all benchmark figures."""
    if not os.path.exists(FIGURES_DIR):
        os.makedirs(FIGURES_DIR, exist_ok=True)

    with open(summary_json_path, "r") as f:
        summary_data = json.load(f)

    plot_load_distribution(summary_data, os.path.join(FIGURES_DIR, "load_distribution_comparison.png"))
    plot_latency_cdf(summary_data, os.path.join(FIGURES_DIR, "latency_cdf.png"))
    plot_fairness_comparison(summary_data, os.path.join(FIGURES_DIR, "fairness_index_comparison.png"))
    plot_throughput_comparison(summary_data, os.path.join(FIGURES_DIR, "throughput_comparison.png"))

if __name__ == "__main__":
    default_json = os.path.join(PROJECT_ROOT, "benchmark", "results", "summary_metrics.json")
    if os.path.exists(default_json):
        generate_all_plots(default_json)
    else:
        print(f"Summary file not found at {default_json}. Run benchmark/run_all_benchmarks.py first.")
