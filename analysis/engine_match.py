"""
engine_match.py

Play full games between Deeper-Blue and an external UCI engine to
benchmark real playing strength — not just single-move comparisons.

Supported opponents:
  - Any UCI-compatible engine (Crafty, Komodo, Fritz, etc.)
  - Stockfish with UCI_LimitStrength + UCI_Elo to simulate era-appropriate
    opponents (e.g. UCI_Elo=2200 approximates a strong 1990s engine)

Usage:
    from analysis.engine_match import EngineMatch

    match = EngineMatch(
        opponent_path="stockfish/stockfish.exe",
        n_games=10,
        time_per_move=2.0,
        depth=4,
        opponent_elo=2200,
    )
    result = match.play_match()
    print(result.summary())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import chess
import chess.engine

from engine.minimax import SearchEngine


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

@dataclass
class GameResult:
    game_number: int
    our_color: chess.Color
    result: str          # "win" | "draw" | "loss"
    termination: str     # "checkmate", "stalemate", "repetition", etc.
    half_moves: int


@dataclass
class MatchResult:
    opponent_name: str
    opponent_elo: int | None
    game_results: list[GameResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.game_results)

    @property
    def wins(self) -> int:
        return sum(1 for g in self.game_results if g.result == "win")

    @property
    def draws(self) -> int:
        return sum(1 for g in self.game_results if g.result == "draw")

    @property
    def losses(self) -> int:
        return sum(1 for g in self.game_results if g.result == "loss")

    @property
    def score(self) -> float:
        """Traditional chess score: win=1, draw=0.5, loss=0."""
        return self.wins + self.draws * 0.5

    @property
    def score_pct(self) -> float:
        return self.score / self.total if self.total > 0 else 0.0

    def summary(self) -> str:
        elo_str = f" (ELO {self.opponent_elo})" if self.opponent_elo else ""
        lines = [
            "=" * 60,
            f"  DEEPER-BLUE vs {self.opponent_name}{elo_str}",
            "=" * 60,
            f"  Games played : {self.total}",
            f"  Score        : {self.score:.1f}/{self.total}  "
            f"({self.wins}W / {self.draws}D / {self.losses}L)",
            f"  Score %      : {self.score_pct:.1%}",
            "",
            "  Game-by-game:",
        ]
        for g in self.game_results:
            color_str = "White" if g.our_color == chess.WHITE else "Black"
            symbol = {"win": "W", "draw": "D", "loss": "L"}[g.result]
            lines.append(
                f"    Game {g.game_number:2d} ({color_str}): "
                f"{symbol}  [{g.termination}, {g.half_moves // 2} moves]"
            )
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine match orchestrator
# ---------------------------------------------------------------------------

_TERMINATION_NAMES = {
    chess.Termination.CHECKMATE:             "checkmate",
    chess.Termination.STALEMATE:             "stalemate",
    chess.Termination.INSUFFICIENT_MATERIAL: "insufficient_material",
    chess.Termination.SEVENTYFIVE_MOVES:     "75_moves",
    chess.Termination.FIVEFOLD_REPETITION:   "5fold_repetition",
    chess.Termination.FIFTY_MOVES:           "50_moves",
    chess.Termination.THREEFOLD_REPETITION:  "3fold_repetition",
}

MAX_HALF_MOVES = 400  # safety limit (~200 moves per side)


class EngineMatch:
    """
    Orchestrates a match between Deeper-Blue and a UCI opponent.

    Parameters
    ----------
    opponent_path : str
        Path to the opponent's UCI engine binary.
    n_games : int
        Number of games to play (we alternate colors each game).
    time_per_move : float
        Seconds allocated per move for both engines.
    depth : int
        Max search depth for Deeper-Blue.
    opponent_elo : int | None
        If set, configure Stockfish's UCI_LimitStrength to simulate
        this ELO.  Ignored for other engines.
    """

    def __init__(
        self,
        opponent_path: str,
        n_games: int = 10,
        time_per_move: float = 2.0,
        depth: int = 4,
        opponent_elo: int | None = None,
    ) -> None:
        self.opponent_path = opponent_path
        self.n_games = n_games
        self.time_per_move = time_per_move
        self.depth = depth
        self.opponent_elo = opponent_elo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play_match(self, verbose: bool = True) -> MatchResult:
        """Play n_games games and return aggregated results."""
        import os
        opponent_name = os.path.basename(self.opponent_path).split(".")[0]
        result = MatchResult(opponent_name=opponent_name, opponent_elo=self.opponent_elo)

        with chess.engine.SimpleEngine.popen_uci(self.opponent_path) as opponent:
            self._configure_opponent(opponent)

            for i in range(self.n_games):
                our_color = chess.WHITE if i % 2 == 0 else chess.BLACK
                color_str = "White" if our_color == chess.WHITE else "Black"

                if verbose:
                    print(f"  Game {i + 1}/{self.n_games} (Deeper-Blue plays {color_str})...",
                          end=" ", flush=True)

                t0 = time.time()
                game_result = self._play_game(i + 1, our_color, opponent)
                elapsed = time.time() - t0

                result.game_results.append(game_result)

                if verbose:
                    symbol = {"win": "W", "draw": "D", "loss": "L"}[game_result.result]
                    print(
                        f"{symbol}  [{game_result.termination}, "
                        f"{game_result.half_moves // 2} moves, {elapsed:.0f}s]"
                    )

        return result

    # ------------------------------------------------------------------
    # Single game
    # ------------------------------------------------------------------

    def _play_game(
        self,
        game_number: int,
        our_color: chess.Color,
        opponent: chess.engine.SimpleEngine,
    ) -> GameResult:
        board = chess.Board()
        our_engine = SearchEngine()
        half_moves = 0

        while not board.is_game_over() and half_moves < MAX_HALF_MOVES:
            if board.turn == our_color:
                move, _ = our_engine.search(
                    board,
                    max_depth=self.depth,
                    time_limit=self.time_per_move,
                )
                if move is None:
                    break
            else:
                result = opponent.play(
                    board,
                    chess.engine.Limit(time=self.time_per_move),
                )
                move = result.move
                if move is None:
                    break

            board.push(move)
            half_moves += 1

        # Determine outcome
        outcome = board.outcome()
        termination = "move_limit" if half_moves >= MAX_HALF_MOVES else "unknown"
        if outcome:
            termination = _TERMINATION_NAMES.get(outcome.termination, "unknown")

        result_str = "draw"
        if outcome and outcome.winner == our_color:
            result_str = "win"
        elif outcome and outcome.winner is not None and outcome.winner != our_color:
            result_str = "loss"

        return GameResult(
            game_number=game_number,
            our_color=our_color,
            result=result_str,
            termination=termination,
            half_moves=half_moves,
        )

    # ------------------------------------------------------------------
    # Opponent configuration
    # ------------------------------------------------------------------

    def _configure_opponent(self, opponent: chess.engine.SimpleEngine) -> None:
        """Apply ELO limiting if requested (Stockfish-specific options)."""
        if self.opponent_elo is None:
            return
        try:
            opponent.configure({
                "UCI_LimitStrength": True,
                "UCI_Elo": self.opponent_elo,
            })
        except chess.engine.EngineError:
            pass   # engine doesn't support strength limiting — play at full strength
