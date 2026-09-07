"""
Jain's Fairness Index Calculator
Implements standard and weighted Jain's Fairness Index for load balancing evaluation.
Formula: J(x) = (sum(x_i))^2 / (n * sum(x_i^2))
Values range from 1/n (worst, all load to one node) to 1.0 (perfectly fair balance).
"""

import numpy as np

def calculate_jains_fairness(counts):
    """
    Calculate standard Jain's Fairness Index.
    :param counts: list or array of numeric values (requests or bytes per server)
    :return: float between 0.0 and 1.0
    """
    x = np.array(list(counts), dtype=float)
    n = len(x)
    if n == 0 or np.sum(x) == 0:
        return 0.0

    sum_x = np.sum(x)
    sum_x_sq = np.sum(x ** 2)

    if sum_x_sq == 0:
        return 0.0

    jfi = (sum_x ** 2) / (n * sum_x_sq)
    return float(round(jfi, 4))

def calculate_weighted_fairness(counts_dict, weights_dict):
    """
    Calculate Weighted Jain's Fairness Index.
    Normalizes each backend's observed load by its configured weight.
    y_i = x_i / w_i
    :param counts_dict: dict of {server_id: count}
    :param weights_dict: dict of {server_id: weight}
    :return: float between 0.0 and 1.0
    """
    normalized = []
    for srv_id, count in counts_dict.items():
        weight = weights_dict.get(srv_id, 1)
        normalized.append(count / float(max(1, weight)))

    return calculate_jains_fairness(normalized)

if __name__ == "__main__":
    # Smoke test calculations
    perfect_rr = [25, 25, 25, 25]
    print(f"Perfect Equal Balance JFI: {calculate_jains_fairness(perfect_rr)} (expected: 1.0)")

    skewed = [100, 0, 0, 0]
    print(f"Completely Skewed Balance JFI: {calculate_jains_fairness(skewed)} (expected: 0.25)")

    weighted_counts = {"srv1": 10, "srv2": 20, "srv3": 10, "srv4": 20}
    weights = {"srv1": 1, "srv2": 2, "srv3": 1, "srv4": 2}
    print(f"Weighted Balance JFI: {calculate_weighted_fairness(weighted_counts, weights)} (expected: 1.0)")
