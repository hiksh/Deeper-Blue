"""
visualizer.py

Visualization of comparison results between Deeper-Blue and Deep Blue (1997).

Charts
------
1. win_rate_by_game    : 게임별 우리 승률 막대그래프
2. delta_distribution  : centipawn delta 분포 (미들/엔드게임 구분)
3. score_timeline      : 게임별 수 진행에 따른 centipawn delta 라인차트
4. phase_breakdown     : 미들/엔드게임 구간별 승/무/패 누적 막대그래프
"""

from __future__ import annotations

from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from analysis.comparator import ComparisonReport, MoveComparison

# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------
COLOR_OURS = "#2196F3"       # blue
COLOR_DB   = "#F44336"       # red
COLOR_DRAW = "#9E9E9E"       # grey
COLOR_MID  = "#4CAF50"       # green  (middlegame)
COLOR_END  = "#FF9800"       # orange (endgame)


# ---------------------------------------------------------------------------
# 1. Win rate by game
# ---------------------------------------------------------------------------

def plot_win_rate_by_game(report: ComparisonReport, save_path: str | None = None) -> None:
    """
    게임별 우리 엔진 승률 막대그래프.
    각 막대는 해당 게임에서 우리가 더 좋은 수를 둔 비율.
    """
    by_game: dict[str, list[MoveComparison]] = defaultdict(list)
    for c in report.comparisons:
        by_game[c.game_id].append(c)

    game_ids = sorted(by_game.keys())
    win_rates = []
    draw_rates = []
    lose_rates = []

    for gid in game_ids:
        comps = by_game[gid]
        total = len(comps)
        win_rates.append(sum(1 for c in comps if c.winner == "ours") / total * 100)
        draw_rates.append(sum(1 for c in comps if c.winner == "equal") / total * 100)
        lose_rates.append(sum(1 for c in comps if c.winner == "deep_blue") / total * 100)

    x = np.arange(len(game_ids))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - width, win_rates,  width, label="Deeper-Blue wins", color=COLOR_OURS,  alpha=0.85)
    ax.bar(x,          draw_rates, width, label="Equal",            color=COLOR_DRAW,  alpha=0.85)
    ax.bar(x + width,  lose_rates, width, label="Deep Blue wins",   color=COLOR_DB,    alpha=0.85)

    ax.set_xlabel("Game")
    ax.set_ylabel("Percentage (%)")
    ax.set_title("Move Quality Comparison per Game\n(Deeper-Blue vs Deep Blue 1997)")
    ax.set_xticks(x)
    ax.set_xticklabels([g.replace("game", "Game ") for g in game_ids])
    ax.set_ylim(0, 100)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    # Annotate total positions per game
    for i, gid in enumerate(game_ids):
        ax.text(i, 102, f"n={len(by_game[gid])}", ha="center", fontsize=8, color="gray")

    plt.tight_layout()
    _save_or_show(fig, save_path)


# ---------------------------------------------------------------------------
# 2. Delta distribution (histogram)
# ---------------------------------------------------------------------------

def plot_delta_distribution(report: ComparisonReport, save_path: str | None = None) -> None:
    """
    centipawn delta (our_score - db_score) 분포 히스토그램.
    미들게임(초록)과 엔드게임(주황)을 겹쳐 표시.
    delta > 0 → 우리가 더 좋은 수.
    """
    mid_deltas = [c.delta for c in report.comparisons if c.phase == "middlegame"]
    end_deltas = [c.delta for c in report.comparisons if c.phase == "endgame"]

    fig, ax = plt.subplots(figsize=(10, 5))

    bins = np.linspace(-400, 400, 41)

    if mid_deltas:
        ax.hist(mid_deltas, bins=bins, alpha=0.6, color=COLOR_MID,  label=f"Middlegame (n={len(mid_deltas)})")
    if end_deltas:
        ax.hist(end_deltas, bins=bins, alpha=0.6, color=COLOR_END, label=f"Endgame (n={len(end_deltas)})")

    ax.axvline(0, color="black", linestyle="--", linewidth=1.2, label="Equal")
    mean_val = np.mean([c.delta for c in report.comparisons]) if report.comparisons else 0
    ax.axvline(mean_val, color="navy", linestyle=":", linewidth=1.5,
               label=f"Mean delta ({report.avg_delta:+.1f} cp)")

    ax.set_xlabel("Centipawn Delta  (our move − Deep Blue move)")
    ax.set_ylabel("Count")
    ax.set_title("Distribution of Move Quality Delta\n(positive = Deeper-Blue better)")
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    _save_or_show(fig, save_path)


# ---------------------------------------------------------------------------
# 3. Score timeline per game
# ---------------------------------------------------------------------------

def plot_score_timeline(report: ComparisonReport, save_path: str | None = None) -> None:
    """
    각 게임에서 수 진행에 따른 centipawn delta 라인차트.
    서브플롯으로 게임별 배치.
    """
    by_game: dict[str, list[MoveComparison]] = defaultdict(list)
    for c in report.comparisons:
        by_game[c.game_id].append(c)

    game_ids = sorted(by_game.keys())
    n = len(game_ids)
    if n == 0:
        return

    cols = 2
    rows = (n + 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(14, 4 * rows), squeeze=False)

    for idx, gid in enumerate(game_ids):
        ax = axes[idx // cols][idx % cols]
        comps = sorted(by_game[gid], key=lambda c: c.move_number)
        moves = [c.move_number for c in comps]
        deltas = [c.delta for c in comps]
        phases = [c.phase for c in comps]

        # Color each point by phase
        colors = [COLOR_MID if p == "middlegame" else COLOR_END for p in phases]

        ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
        ax.plot(moves, deltas, color="steelblue", linewidth=1.2, alpha=0.6)
        ax.scatter(moves, deltas, c=colors, s=30, zorder=3)
        ax.fill_between(moves, deltas, 0,
                        where=[d > 0 for d in deltas], alpha=0.15, color=COLOR_OURS,
                        label="Our advantage")
        ax.fill_between(moves, deltas, 0,
                        where=[d < 0 for d in deltas], alpha=0.15, color=COLOR_DB,
                        label="DB advantage")

        ax.set_title(gid.replace("game", "Game "))
        ax.set_xlabel("Move number")
        ax.set_ylabel("Delta (cp)")
        ax.grid(alpha=0.3)

    # Hide unused subplots
    for idx in range(n, rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)

    # Common legend
    mid_patch = mpatches.Patch(color=COLOR_MID, label="Middlegame position")
    end_patch = mpatches.Patch(color=COLOR_END, label="Endgame position")
    fig.legend(handles=[mid_patch, end_patch], loc="lower right", fontsize=9)

    fig.suptitle("Centipawn Delta per Move  (Deeper-Blue vs Deep Blue 1997)", fontsize=13)
    plt.tight_layout()
    _save_or_show(fig, save_path)


# ---------------------------------------------------------------------------
# 4. Phase breakdown (stacked bar)
# ---------------------------------------------------------------------------

def plot_phase_breakdown(report: ComparisonReport, save_path: str | None = None) -> None:
    """
    미들/엔드게임 구간별 승/무/패 누적 막대그래프.
    """
    phases = ["middlegame", "endgame", "overall"]
    labels = ["Middlegame", "Endgame", "Overall"]

    def counts(comps):
        total = len(comps)
        if total == 0:
            return 0, 0, 0
        w = sum(1 for c in comps if c.winner == "ours") / total * 100
        d = sum(1 for c in comps if c.winner == "equal") / total * 100
        l = sum(1 for c in comps if c.winner == "deep_blue") / total * 100
        return w, d, l

    wins, draws, losses = [], [], []
    for ph in phases:
        sub = [c for c in report.comparisons if c.phase == ph] if ph != "overall" else report.comparisons
        w, d, l = counts(sub)
        wins.append(w)
        draws.append(d)
        losses.append(l)

    x = np.arange(len(phases))
    fig, ax = plt.subplots(figsize=(8, 5))

    bars_w = ax.bar(x, wins,   label="Deeper-Blue wins", color=COLOR_OURS, alpha=0.85)
    bars_d = ax.bar(x, draws,  bottom=wins,              label="Equal",    color=COLOR_DRAW, alpha=0.85)
    bars_l = ax.bar(x, losses, bottom=[w + d for w, d in zip(wins, draws)],
                    label="Deep Blue wins", color=COLOR_DB, alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Percentage (%)")
    ax.set_ylim(0, 105)
    ax.set_title("Move Quality by Game Phase\n(Deeper-Blue vs Deep Blue 1997)")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)

    # Annotate percentages inside bars
    for i, (w, d, l) in enumerate(zip(wins, draws, losses)):
        if w > 5:
            ax.text(i, w / 2,        f"{w:.0f}%", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
        if d > 5:
            ax.text(i, w + d / 2,    f"{d:.0f}%", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
        if l > 5:
            ax.text(i, w + d + l / 2, f"{l:.0f}%", ha="center", va="center", color="white", fontsize=9, fontweight="bold")

    plt.tight_layout()
    _save_or_show(fig, save_path)


# ---------------------------------------------------------------------------
# Convenience: plot all charts at once
# ---------------------------------------------------------------------------

def plot_all(report: ComparisonReport, output_dir: str | None = None) -> None:
    """모든 차트를 한 번에 출력하거나 output_dir에 저장."""
    import os

    def path(name):
        return os.path.join(output_dir, name) if output_dir else None

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    plot_win_rate_by_game(report,    save_path=path("win_rate_by_game.png"))
    plot_delta_distribution(report,  save_path=path("delta_distribution.png"))
    plot_score_timeline(report,      save_path=path("score_timeline.png"))
    plot_phase_breakdown(report,     save_path=path("phase_breakdown.png"))

    if not output_dir:
        plt.show()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _save_or_show(fig: plt.Figure, save_path: str | None) -> None:
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
        plt.close(fig)
