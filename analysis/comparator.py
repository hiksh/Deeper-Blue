"""
comparator.py

Compares our engine's move against Deep Blue's historical move
using Stockfish as an objective evaluator (centipawn scores).

Comparison logic
-----------------
For each position:
  1. Our engine (SearchEngine) selects its best move.
  2. Deep Blue's actual move is taken from the PGN record.
  3. Both moves are applied to the position and Stockfish evaluates
     the resulting positions.
  4. The move with the higher Stockfish score (from Deep Blue's side's
     perspective) is declared the winner.

A positive delta (our_score - db_score) means our move was better.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field

import chess
import chess.engine

from analysis.pgn_parser import PositionRecord, GameRecord
from engine.minimax import SearchEngine

# ---------------------------------------------------------------------------
# Default Stockfish paths
# ---------------------------------------------------------------------------
_STOCKFISH_DEFAULTS = {
    "Windows": [
        r"stockfish\stockfish.exe",
        r"C:\Program Files\Stockfish\stockfish.exe",
    ],
    "Linux": [
        "stockfish/stockfish",
        "/usr/bin/stockfish",
        "/usr/local/bin/stockfish",
    ],
    "Darwin": [
        "stockfish/stockfish",
        "/usr/local/bin/stockfish",
        "/opt/homebrew/bin/stockfish",
    ],
}


def find_stockfish(custom_path: str | None = None) -> str:
    """
    Locate the Stockfish binary.
    Raises FileNotFoundError if not found.
    """
    if custom_path:
        if os.path.isfile(custom_path):
            return custom_path
        raise FileNotFoundError(f"Stockfish not found at: {custom_path}")

    system = platform.system()
    candidates = _STOCKFISH_DEFAULTS.get(system, [])

    # Also search relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [os.path.join(project_root, c) if not os.path.isabs(c) else c
                  for c in candidates]

    for path in candidates:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Stockfish binary not found. Please download it from "
        "https://stockfishchess.org/download/ and place it in the "
        "'stockfish/' directory, or pass --stockfish <path>."
    )


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

@dataclass
class MoveComparison:
    """Result of comparing one move pair."""
    game_id: str
    move_number: int
    phase: str
    fen: str
    our_move: str              # UCI notation
    deep_blue_move: str        # UCI notation
    our_score: int             # centipawns after our move (from mover's perspective)
    deep_blue_score: int       # centipawns after DB's move (from mover's perspective)
    delta: int                 # our_score - deep_blue_score (positive = we're better)
    winner: str                # "ours", "deep_blue", or "equal"


@dataclass
class ComparisonReport:
    """Aggregated results over all positions."""
    comparisons: list[MoveComparison] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.comparisons)

    @property
    def our_wins(self) -> int:
        return sum(1 for c in self.comparisons if c.winner == "ours")

    @property
    def db_wins(self) -> int:
        return sum(1 for c in self.comparisons if c.winner == "deep_blue")

    @property
    def draws(self) -> int:
        return sum(1 for c in self.comparisons if c.winner == "equal")

    @property
    def win_rate(self) -> float:
        return self.our_wins / self.total if self.total > 0 else 0.0

    @property
    def avg_delta(self) -> float:
        if not self.comparisons:
            return 0.0
        return sum(c.delta for c in self.comparisons) / self.total

    def by_phase(self, phase: str) -> "ComparisonReport":
        sub = ComparisonReport()
        sub.comparisons = [c for c in self.comparisons if c.phase == phase]
        return sub

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  DEEPER-BLUE vs DEEP BLUE (1997) -- Comparison Report",
            "=" * 60,
            f"  Positions analysed : {self.total}",
            f"  Our wins           : {self.our_wins} ({self.win_rate:.1%})",
            f"  Deep Blue wins     : {self.db_wins}",
            f"  Equal              : {self.draws}",
            f"  Average delta      : {self.avg_delta:+.1f} cp",
            "",
        ]
        for phase in ["middlegame", "endgame"]:
            sub = self.by_phase(phase)
            if sub.total:
                lines.append(
                    f"  [{phase.capitalize():12s}] "
                    f"Ours {sub.our_wins}/{sub.total} "
                    f"({sub.win_rate:.1%}), "
                    f"avg delta {sub.avg_delta:+.1f} cp"
                )
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comparator
# ---------------------------------------------------------------------------

# Equality threshold: differences ≤ this many centipawns are considered equal
EQUALITY_THRESHOLD_CP = 10

# Stockfish analysis time per position (seconds)
# 0.5s gives a reasonable accuracy vs speed tradeoff for a comparison tool.
STOCKFISH_ANALYSIS_TIME = 0.5

# Our engine search depth
ENGINE_DEPTH = 4
ENGINE_TIME_LIMIT = 5.0


class Comparator:
    """
    Orchestrates the comparison between our engine and Deep Blue's moves.
    """

    def __init__(
        self,
        stockfish_path: str | None = None,
        engine_depth: int = ENGINE_DEPTH,
        engine_time: float = ENGINE_TIME_LIMIT,
        stockfish_time: float = STOCKFISH_ANALYSIS_TIME,
        equality_threshold: int = EQUALITY_THRESHOLD_CP,
    ) -> None:
        self.sf_path = find_stockfish(stockfish_path)
        self.engine_depth = engine_depth
        self.engine_time = engine_time
        self.sf_time = stockfish_time
        self.eq_threshold = equality_threshold
        self._our_engine = SearchEngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare_positions(
        self,
        positions: list[PositionRecord],
        verbose: bool = False,
    ) -> ComparisonReport:
        """
        Run comparison over a list of PositionRecords.
        Opens one Stockfish process for the entire batch (more efficient).
        """
        report = ComparisonReport()
        total = len(positions)

        with chess.engine.SimpleEngine.popen_uci(self.sf_path) as sf:
            for i, pos in enumerate(positions, 1):
                if not verbose:
                    print(f"\r  Analysing position {i}/{total}...", end="", flush=True)
                try:
                    result = self._compare_one(pos, sf, verbose)
                except Exception as exc:
                    print(f"\n  [WARN] Skipped {pos.game_id} move {pos.move_number}: {exc}")
                    continue
                if result is not None:
                    report.comparisons.append(result)

        if not verbose:
            print()  # newline after progress indicator
        return report

    def compare_game_records(
        self,
        records: list[GameRecord],
        verbose: bool = False,
    ) -> ComparisonReport:
        """Convenience wrapper: flatten GameRecords then compare."""
        all_positions = [p for r in records for p in r.positions]
        return self.compare_positions(all_positions, verbose)

    # ------------------------------------------------------------------
    # Single-position comparison
    # ------------------------------------------------------------------

    def _compare_one(
        self,
        pos: PositionRecord,
        sf: chess.engine.SimpleEngine,
        verbose: bool,
    ) -> MoveComparison | None:
        board = chess.Board(pos.fen)

        # --- Our engine's move ---
        self._our_engine.tt.clear()
        our_move, _ = self._our_engine.search(
            board, max_depth=self.engine_depth, time_limit=self.engine_time
        )
        if our_move is None:
            return None  # No legal moves (shouldn't happen for non-terminal positions)

        # --- Validate Deep Blue's move ---
        try:
            db_move = chess.Move.from_uci(pos.deep_blue_move)
            if db_move not in board.legal_moves:
                return None
        except ValueError:
            return None

        # --- Stockfish evaluation after each move ---
        our_score = self._sf_eval(board, our_move, sf)
        db_score = self._sf_eval(board, db_move, sf)

        delta = our_score - db_score

        if abs(delta) <= self.eq_threshold:
            winner = "equal"
        elif delta > 0:
            winner = "ours"
        else:
            winner = "deep_blue"

        comparison = MoveComparison(
            game_id=pos.game_id,
            move_number=pos.move_number,
            phase=pos.phase,
            fen=pos.fen,
            our_move=our_move.uci(),
            deep_blue_move=pos.deep_blue_move,
            our_score=our_score,
            deep_blue_score=db_score,
            delta=delta,
            winner=winner,
        )

        if verbose:
            side = "White" if pos.color == chess.WHITE else "Black"
            print(
                f"  [{pos.game_id} move {pos.move_number} {side} | {pos.phase}]  "
                f"ours={our_move.uci()} ({our_score:+d}cp)  "
                f"DB={pos.deep_blue_move} ({db_score:+d}cp)  "
                f"delta={delta:+d}  → {winner}"
            )

        return comparison

    # ------------------------------------------------------------------
    # Stockfish helper
    # ------------------------------------------------------------------

    def _sf_eval(
        self,
        board: chess.Board,
        move: chess.Move,
        sf: chess.engine.SimpleEngine,
    ) -> int:
        """
        Apply `move` to a copy of `board`, ask Stockfish to evaluate,
        and return the score in centipawns from the perspective of the
        side that just moved (i.e., the side that played `move`).
        """
        b = board.copy()
        b.push(move)

        info = sf.analyse(b, chess.engine.Limit(time=self.sf_time))
        score = info["score"]

        # Convert to centipawns from the perspective of the side that moved
        # score.white() gives White's perspective
        cp = score.white().score(mate_score=30000)
        if cp is None:
            cp = 0

        # Flip if the mover was Black (we want mover's perspective)
        if board.turn == chess.BLACK:
            cp = -cp

        return cp
