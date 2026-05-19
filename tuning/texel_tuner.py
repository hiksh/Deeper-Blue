"""
tuning/texel_tuner.py

Texel Tuning: minimize MSE between sigmoid(eval/K) and game result.

Reference: https://www.chessprogramming.org/Texel%27s_Tuning_Method

Algorithm:
  E(params) = mean((result - sigmoid(eval(fen, params) / K))^2)
  Minimized with scipy L-BFGS-B using parallel position evaluation.

Usage (server — A100 with many cores):
    python main.py tune --positions data/positions.json.gz --workers 48 --iter 300

Usage (scalar-only, faster):
    python main.py tune --positions data/positions.json.gz --no-pst

After tuning, the best params are saved to a JSON file and can be loaded by the engine.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

import chess
from engine.evaluation import EvalParams, evaluate_with_params

# Centipawn scale for win probability sigmoid.
# sigmoid(score) = 1 / (1 + 10^(-score/K))
# K=400 means a 400cp advantage gives ~91% win probability.
_SIGMOID_K = 200.0


# ---------------------------------------------------------------------------
# Worker functions (module-level for pickling compatibility)
# ---------------------------------------------------------------------------

def _eval_chunk(chunk: list, params: EvalParams) -> float:
    """Evaluate a list of (fen, result) and return mean squared error."""
    total = 0.0
    for fen, result in chunk:
        board = chess.Board(fen)
        score = evaluate_with_params(board, params)
        pred = 1.0 / (1.0 + 10.0 ** (-score / _SIGMOID_K))
        total += (result - pred) ** 2
    return total / len(chunk)


# ---------------------------------------------------------------------------
# Loss function
# ---------------------------------------------------------------------------

def texel_loss(
    params_vector: np.ndarray,
    positions: list,
    chunks: list,
    n_workers: int,
    include_pst: bool,
    executor: concurrent.futures.Executor,
) -> float:
    """Mean squared error over all positions. Called by scipy minimize."""
    params = EvalParams.from_vector(params_vector, include_pst=include_pst)
    futures = [executor.submit(_eval_chunk, chunk, params) for chunk in chunks]
    chunk_means = [f.result() for f in futures]
    return float(np.mean(chunk_means))


# ---------------------------------------------------------------------------
# Bounds for scipy L-BFGS-B
# ---------------------------------------------------------------------------

def _get_bounds(include_pst: bool) -> list[tuple[float, float]]:
    """Per-parameter lower/upper bounds (keeps tuning numerically stable)."""
    scalar_bounds = [
        (50,  200),   # pawn
        (200, 500),   # knight
        (200, 500),   # bishop
        (350, 700),   # rook
        (700, 1200),  # queen
        (0,   120),   # bishop_pair
        (0,    60),   # rook_open_file
        (0,    40),   # rook_semi_open
        (0,    60),   # rook_7th
        (0,    60),   # outpost_knight
        (0,    40),   # outpost_bishop
        (0,    40),   # outpost_pawn_supp
        (0,    60),   # connected_rooks
        (0,    10),   # mobility_sq
        (0,    60),   # doubled_pawn
        (0,    70),   # isolated_pawn
        (0,    60),   # backward_pawn
        (0,    40),   # passed_r1
        (0,    80),   # passed_r2
        (0,   120),   # passed_r3
        (0,   200),   # passed_r4
        (0,   300),   # passed_r5
        (0,   500),   # passed_r6
        (0,    40),   # king_shield
        (0,    50),   # king_open_file
        (0,    30),   # king_eg_center
    ]
    if not include_pst:
        return scalar_bounds
    pst_bounds = [(-150.0, 150.0)] * (8 * 64)
    return scalar_bounds + pst_bounds


# ---------------------------------------------------------------------------
# Main tuning entry point
# ---------------------------------------------------------------------------

def tune(
    positions: list[tuple[str, float]],
    initial_params: EvalParams | None = None,
    include_pst: bool = False,
    n_workers: int | None = None,
    max_iter: int = 300,
) -> EvalParams:
    """Run Texel tuning and return optimized EvalParams.

    Args:
        positions:      List of (fen, result) training positions.
        initial_params: Starting point (defaults to hand-tuned values).
        include_pst:    Also tune all 8 PST tables (538 params total).
        n_workers:      CPU workers for parallel eval (default: all cores).
        max_iter:       Maximum L-BFGS-B iterations.

    Returns:
        Optimized EvalParams.
    """
    if n_workers is None:
        n_workers = os.cpu_count() or 4

    p0 = (initial_params or EvalParams()).to_vector(include_pst=include_pst)
    bounds = _get_bounds(include_pst)
    n_params = len(p0)

    # Chunk positions for efficient parallel evaluation
    chunk_size = max(256, len(positions) // (n_workers * 8))
    chunks = [positions[i: i + chunk_size] for i in range(0, len(positions), chunk_size)]

    print(f"  Positions   : {len(positions):,}")
    print(f"  Parameters  : {n_params} ({'scalars + PST' if include_pst else 'scalars only'})")
    print(f"  Workers     : {n_workers}")
    print(f"  Chunks      : {len(chunks)} × ~{chunk_size} positions")
    print(f"  Max iter    : {max_iter}\n")

    call_count = [0]
    t_start = time.time()

    with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as executor:
        def loss(v: np.ndarray) -> float:
            call_count[0] += 1
            mse = texel_loss(v, positions, chunks, n_workers, include_pst, executor)
            elapsed = time.time() - t_start
            print(
                f"\r  Step {call_count[0]:4d} | MSE {mse:.7f} | {elapsed:.0f}s elapsed",
                end="", flush=True,
            )
            return mse

        result = minimize(
            loss,
            p0,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": max_iter, "ftol": 1e-10, "gtol": 1e-7},
        )

    print(f"\n\n  Optimization finished: {result.message}")
    print(f"  Final MSE: {result.fun:.7f}")

    return EvalParams.from_vector(result.x, include_pst=include_pst)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_params(params: EvalParams, path: str | Path) -> None:
    """Save EvalParams to JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(params.to_dict(), f, indent=2)
    print(f"  Params saved to: {path}")


def load_params(path: str | Path) -> EvalParams:
    """Load EvalParams from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return EvalParams.from_dict(d)


# ---------------------------------------------------------------------------
# Diff report: show what changed vs defaults
# ---------------------------------------------------------------------------

def print_diff(tuned: EvalParams, baseline: EvalParams | None = None) -> None:
    """Print a table comparing tuned params vs baseline (default if None)."""
    baseline = baseline or EvalParams()
    scalar_fields = [
        "pawn", "knight", "bishop", "rook", "queen",
        "bishop_pair", "rook_open_file", "rook_semi_open", "rook_7th",
        "outpost_knight", "outpost_bishop", "outpost_pawn_supp", "connected_rooks",
        "mobility_sq", "doubled_pawn", "isolated_pawn", "backward_pawn",
        "passed_r1", "passed_r2", "passed_r3", "passed_r4", "passed_r5", "passed_r6",
        "king_shield", "king_open_file", "king_eg_center",
    ]
    print("\n  Parameter              Before  After   Change")
    print("  " + "-" * 45)
    for name in scalar_fields:
        old = getattr(baseline, name)
        new = getattr(tuned, name)
        diff = new - old
        marker = " *" if abs(diff) >= 5 else ""
        print(f"  {name:22s}  {old:5d}  {new:5d}  {diff:+6d}{marker}")
