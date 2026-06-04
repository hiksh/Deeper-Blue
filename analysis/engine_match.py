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

import concurrent.futures
import os
import signal
import time
from dataclasses import dataclass, field

import chess
import chess.engine

from engine.minimax import SearchEngine

# Shared thread pool used to run blocking engine.play() calls under a
# wall-clock watchdog.  When a move exceeds the watchdog timeout the engine
# is considered hung; we kill its process (which unblocks the worker thread)
# and abort that game.
_WATCHDOG_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _timed_move(engine, board, limit, watchdog_s):
    """
    Run engine.play(board, limit) but give up after watchdog_s seconds.

    Returns (move, hung): hung=True if the watchdog fired or the engine
    raised — in both cases the caller should kill+restart the engine and
    discard the game.
    """
    fut = _WATCHDOG_EXEC.submit(engine.play, board, limit)
    try:
        res = fut.result(timeout=watchdog_s)
        return res.move, False
    except concurrent.futures.TimeoutError:
        return None, True
    except Exception:
        return None, True


def _kill_engine(engine):
    """Forcibly terminate an engine subprocess (best-effort)."""
    pid = None
    try:
        pid = engine.transport.get_pid()
    except Exception:
        pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)   # Windows: TerminateProcess
        except Exception:
            pass
    try:
        engine.quit()
    except Exception:
        pass


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
    c_engine_path : str | None
        Path to the compiled C engine binary. If provided, uses it
        instead of the Python SearchEngine.
    """

    def __init__(
        self,
        opponent_path: str,
        n_games: int = 10,
        time_per_move: float = 2.0,
        depth: int = 4,
        opponent_elo: int | None = None,
        c_engine_path: str | None = None,
        watchdog_factor: float = 4.0,
    ) -> None:
        self.opponent_path = opponent_path
        self.n_games = n_games
        self.time_per_move = time_per_move
        self.depth = depth
        self.opponent_elo = opponent_elo
        self.c_engine_path = c_engine_path
        # A move taking longer than max(time_per_move * factor, 25s) is
        # treated as a hang → kill engine, abort & replay the game.
        self.watchdog_s = max(time_per_move * watchdog_factor, 25.0)
        self._our_uci = None
        self._py_engine = None
        self._opp = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play_match(self, verbose: bool = True) -> MatchResult:
        """
        Play games until n_games *complete* normally, returning aggregated
        results.  Games where an engine hangs past the watchdog timeout are
        aborted (engine killed + restarted) and replayed, so the final tally
        contains only clean games.
        """
        opponent_name = os.path.basename(self.opponent_path).split(".")[0]
        result = MatchResult(opponent_name=opponent_name, opponent_elo=self.opponent_elo)

        self._our_uci = self._spawn_our() if self.c_engine_path else None
        self._py_engine = SearchEngine() if not self.c_engine_path else None
        self._opp = self._spawn_opponent()

        aborts = 0
        attempts = 0
        max_attempts = self.n_games * 5

        try:
            while len(result.game_results) < self.n_games and attempts < max_attempts:
                attempts += 1
                idx = len(result.game_results)
                our_color = chess.WHITE if idx % 2 == 0 else chess.BLACK
                color_str = "White" if our_color == chess.WHITE else "Black"

                if verbose:
                    print(f"  Game {idx + 1}/{self.n_games} (Deeper-Blue plays {color_str})...",
                          end=" ", flush=True)

                t0 = time.time()
                game_result = self._play_game(idx + 1, our_color)
                elapsed = time.time() - t0

                if game_result.result == "aborted":
                    aborts += 1
                    if verbose:
                        print(f"ABORTED [watchdog hang on {game_result.termination}, "
                              f"engine restarted, {elapsed:.0f}s] — replaying")
                    continue

                result.game_results.append(game_result)
                if verbose:
                    symbol = {"win": "W", "draw": "D", "loss": "L"}[game_result.result]
                    print(
                        f"{symbol}  [{game_result.termination}, "
                        f"{game_result.half_moves // 2} moves, {elapsed:.0f}s]"
                    )
        finally:
            if verbose and aborts:
                print(f"  ({aborts} game(s) aborted by watchdog and replayed)")
            for e in (self._our_uci, self._opp):
                if e is not None:
                    try:
                        e.quit()
                    except Exception:
                        pass

        return result

    # ------------------------------------------------------------------
    # Engine spawning (with restart support)
    # ------------------------------------------------------------------

    def _spawn_our(self) -> chess.engine.SimpleEngine:
        eng = chess.engine.SimpleEngine.popen_uci(self.c_engine_path)
        book_path = os.path.join(os.path.dirname(self.c_engine_path), "book.bin")
        if os.path.isfile(book_path):
            try:
                eng.configure({"BookFile": book_path, "OwnBook": True})
            except Exception:
                pass
        return eng

    def _spawn_opponent(self) -> chess.engine.SimpleEngine:
        eng = chess.engine.SimpleEngine.popen_uci(self.opponent_path)
        if self.opponent_elo is not None:
            try:
                eng.configure({
                    "UCI_LimitStrength": True,
                    "UCI_Elo": self.opponent_elo,
                })
            except chess.engine.EngineError:
                pass   # engine doesn't support strength limiting
        return eng

    # ------------------------------------------------------------------
    # Single game
    # ------------------------------------------------------------------

    def _play_game(
        self,
        game_number: int,
        our_color: chess.Color,
    ) -> GameResult:
        board = chess.Board()
        half_moves = 0
        limit = chess.engine.Limit(time=self.time_per_move)

        while not board.is_game_over() and half_moves < MAX_HALF_MOVES:
            our_turn = (board.turn == our_color)

            if our_turn and self._our_uci is None:
                # In-process Python engine — no subprocess to watchdog.
                move, _ = self._py_engine.search(
                    board, max_depth=self.depth, time_limit=self.time_per_move
                )
            else:
                engine = self._our_uci if our_turn else self._opp
                move, hung = _timed_move(engine, board, limit, self.watchdog_s)
                if hung:
                    # Kill the stuck engine (frees the worker thread) and
                    # restart it, then abort this game for replay.
                    _kill_engine(engine)
                    side = "our_engine" if our_turn else "opponent"
                    if our_turn:
                        self._our_uci = self._spawn_our()
                    else:
                        self._opp = self._spawn_opponent()
                    return GameResult(
                        game_number=game_number,
                        our_color=our_color,
                        result="aborted",
                        termination=side,
                        half_moves=half_moves,
                    )

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
