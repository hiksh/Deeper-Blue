"""
minimax.py

Core search algorithm for the Deeper-Blue chess engine.

Implements:
  - Negamax framework (sign-unified minimax)
  - Alpha-Beta Pruning (fail-soft)
  - Principal Variation Search (PVS)
  - Iterative Deepening with Aspiration Windows
  - Check Extensions (extend search when in check to avoid missing tactics)
  - Quiescence Search (avoids horizon effect) with delta pruning
  - Late Move Reduction (LMR) with log-based formula
  - Transposition Table (Zobrist-keyed)
  - Null Move Pruning with adaptive reduction
  - Futility Pruning
  - Move ordering via MoveOrderer

Usage:
    engine = SearchEngine()
    best_move, score = engine.search(board, max_depth=5)
"""

import math
import time
import chess
import chess.polyglot

from engine.evaluation import evaluate
from engine.move_ordering import MoveOrderer, see

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INF = 100_000
MATE_SCORE = 30_000
MATE_THRESHOLD = MATE_SCORE - 500   # scores above this indicate forced mate

# Transposition table entry flags
TT_EXACT = 0   # exact score
TT_LOWER = 1   # lower bound (failed high, beta cutoff)
TT_UPPER = 2   # upper bound (failed low, no improvement over alpha)

# Aspiration window initial size (centipawns)
ASPIRATION_WINDOW = 50

# Late Move Reduction (LMR) — log-based formula for adaptive reduction
# reduction = max(1, int(sqrt(depth-1) * sqrt(moves_searched-1)))
# Only reduce when depth >= 3 and moves_searched >= LMR_FULL_SEARCH_MOVES
LMR_MIN_DEPTH = 3          # only reduce at depth >= 3
LMR_FULL_SEARCH_MOVES = 4  # first N moves get full depth

# Check extension: extend search by 1 ply when in check to avoid tactics
CHECK_EXTENSION = 1

# Quiescence delta pruning margin (centipawns)
DELTA_MARGIN = 200

# Futility pruning margins per depth (centipawns)
FUTILITY_MARGINS = {1: 100, 2: 300}

# Null move pruning
NMP_MIN_DEPTH = 3    # only apply at depth >= 3
NMP_BASE_REDUCTION = 2    # base depth reduction (R)


# ---------------------------------------------------------------------------
# Transposition Table
# ---------------------------------------------------------------------------

class TTEntry:
    __slots__ = ("depth", "score", "flag", "best_move")

    def __init__(self, depth: int, score: int, flag: int, best_move: chess.Move | None):
        self.depth = depth
        self.score = score
        self.flag = flag
        self.best_move = best_move


class TranspositionTable:
    """
    Hash map keyed by Zobrist hash (via chess.polyglot.zobrist_hash).
    Uses always-replace scheme — simple and adequate for this scale.
    When the table is full, older entries are evicted.
    """
    MAX_ENTRIES = 1 << 20  # ~1 million entries

    def __init__(self) -> None:
        self._table: dict[int, TTEntry] = {}

    def probe(self, key: int) -> TTEntry | None:
        return self._table.get(key)

    def store(self, key: int, entry: TTEntry) -> None:
        if len(self._table) >= self.MAX_ENTRIES:
            self._table.clear()
        self._table[key] = entry

    def clear(self) -> None:
        self._table.clear()

    @staticmethod
    def key(board: chess.Board) -> int:
        """Public, stable Zobrist hash via python-chess polyglot module."""
        return chess.polyglot.zobrist_hash(board)


# ---------------------------------------------------------------------------
# Search Engine
# ---------------------------------------------------------------------------

class SearchEngine:
    """
    Iterative-deepening alpha-beta search engine with PVS and Check Extensions.

    Public API
    ----------
    search(board, max_depth, time_limit) -> (best_move, score)
    """

    def __init__(self) -> None:
        self.tt = TranspositionTable()
        self.nodes_searched = 0
        self._start_time: float = 0.0
        self._time_limit: float = float("inf")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        board: chess.Board,
        max_depth: int = 5,
        time_limit: float = 10.0,
    ) -> tuple[chess.Move | None, int]:
        """
        Iterative deepening search with aspiration windows.

        Returns (best_move, score) where score is from the side-to-move's
        perspective in centipawns.
        """
        self._start_time = time.time()
        self._time_limit = time_limit
        self.nodes_searched = 0

        best_move: chess.Move | None = None
        best_score = -INF
        orderer = MoveOrderer()

        for depth in range(1, max_depth + 1):
            if self._elapsed() > self._time_limit:
                break

            # Aspiration window: narrow search around previous score.
            # On fail-low/high, widen and retry with full window.
            if depth >= 4 and best_score not in (-INF, INF):
                alpha = best_score - ASPIRATION_WINDOW
                beta = best_score + ASPIRATION_WINDOW
            else:
                alpha, beta = -INF, INF

            score, move = self._root_search(board, depth, orderer, alpha, beta)

            # Re-search with full window if score fell outside aspiration window
            if score <= alpha or score >= beta:
                score, move = self._root_search(board, depth, orderer, -INF, INF)

            if move is not None:
                best_move = move
                best_score = score

            if abs(best_score) >= MATE_THRESHOLD:
                break

        return best_move, best_score

    # ------------------------------------------------------------------
    # Root search
    # ------------------------------------------------------------------

    def _root_search(
        self,
        board: chess.Board,
        depth: int,
        orderer: MoveOrderer,
        alpha: int,
        beta: int,
    ) -> tuple[int, chess.Move | None]:
        best_move = None
        best_score = -INF
        original_alpha = alpha

        tt_key = TranspositionTable.key(board)
        tt_entry = self.tt.probe(tt_key)
        pv_move = tt_entry.best_move if tt_entry else None

        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return self._terminal_score(board, ply=0), None

        ordered = orderer.order_moves(board, legal_moves, ply=0, pv_move=pv_move)

        for idx, move in enumerate(ordered):
            board.push(move)

            if idx == 0:
                # First move: full window search
                score = -self._negamax(board, depth - 1, -beta, -alpha, ply=1, orderer=orderer)
            else:
                # PVS: null window search for subsequent moves
                score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, ply=1, orderer=orderer)
                # Re-search with full window if it improved alpha
                if alpha < score < beta:
                    score = -self._negamax(board, depth - 1, -beta, -alpha, ply=1, orderer=orderer)

            board.pop()

            if score > best_score:
                best_score = score
                best_move = move
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break

        flag = TT_EXACT
        if best_score <= original_alpha:
            flag = TT_UPPER
        elif best_score >= beta:
            flag = TT_LOWER
        self.tt.store(tt_key, TTEntry(depth, best_score, flag, best_move))
        return best_score, best_move

    # ------------------------------------------------------------------
    # Negamax with Alpha-Beta + PVS + LMR + Check Extension
    # ------------------------------------------------------------------

    def _negamax(
        self,
        board: chess.Board,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
        orderer: MoveOrderer,
    ) -> int:
        """
        Fail-soft negamax with Principal Variation Search (PVS).
        Returns score from the side-to-move's perspective.

        Key techniques:
        - Check Extension: extend depth when in check to avoid missing tactics
        - PVS: null window for moves after the first, re-search if they beat alpha
        - LMR: logarithmic reduction formula for late quiet moves
        """
        self.nodes_searched += 1

        # --- Transposition Table probe ---
        tt_key = TranspositionTable.key(board)
        tt_entry = self.tt.probe(tt_key)
        pv_move = None
        if tt_entry is not None:
            pv_move = tt_entry.best_move
            if tt_entry.depth >= depth:
                if tt_entry.flag == TT_EXACT:
                    return tt_entry.score
                elif tt_entry.flag == TT_LOWER:
                    alpha = max(alpha, tt_entry.score)
                elif tt_entry.flag == TT_UPPER:
                    beta = min(beta, tt_entry.score)
                if alpha >= beta:
                    return tt_entry.score

        # --- Terminal check ---
        if board.is_game_over():
            return self._terminal_score(board, ply)

        # --- Check Extension ---
        # When in check, extend by 1 ply to avoid missing forced sequences.
        # Only extend once per path by detecting check BEFORE reducing to 0.
        in_check = board.is_check()
        if in_check and depth <= 0:
            depth = CHECK_EXTENSION  # allow at least one more ply

        # --- Horizon: enter quiescence ---
        if depth <= 0:
            return self._quiescence(board, alpha, beta)

        # --- Periodic time check ---
        if self.nodes_searched & 0xFFF == 0 and self._elapsed() > self._time_limit:
            raw = evaluate(board)
            return raw if board.turn == chess.WHITE else -raw

        # --- Null Move Pruning (NMP) ---
        # If we can skip our move and still cause a beta cutoff, the position
        # is very good for us. Not applied in check or near-endgame (zugzwang risk).
        # Adaptive reduction: R=3 at depth>=6, R=2 otherwise.
        if (
            depth >= NMP_MIN_DEPTH
            and not in_check
            and _count_major_pieces(board, board.turn) >= 2
        ):
            nmp_r = 3 if depth >= 6 else NMP_BASE_REDUCTION
            board.push(chess.Move.null())
            null_score = -self._negamax(
                board, depth - 1 - nmp_r, -beta, -beta + 1, ply + 1, orderer
            )
            board.pop()
            if null_score >= beta:
                return null_score  # fail-soft

        # --- Futility pruning setup ---
        futility_margin = FUTILITY_MARGINS.get(depth)
        do_futility = False
        if futility_margin is not None and not in_check:
            raw = evaluate(board)
            static_eval = raw if board.turn == chess.WHITE else -raw
            if static_eval + futility_margin <= alpha:
                do_futility = True

        # --- Generate and order moves ---
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return self._terminal_score(board, ply)

        ordered = orderer.order_moves(board, legal_moves, ply, pv_move)

        best_score = -INF
        best_move = None
        original_alpha = alpha
        moves_searched = 0

        for move in ordered:
            mover_color = board.turn
            is_capture = board.is_capture(move)
            gives_check = board.gives_check(move)

            # Futility pruning: skip quiet moves that can't improve alpha
            if (
                do_futility
                and not is_capture
                and move.promotion is None
                and not gives_check
                and moves_searched > 0
            ):
                moves_searched += 1
                continue

            board.push(move)

            # --- LMR + PVS integrated ---
            # LMR formula: reduction = max(1, sqrt(depth-1) * sqrt(moves_searched-1))
            # Only for quiet, non-check-giving late moves.
            if (
                depth >= LMR_MIN_DEPTH
                and moves_searched >= LMR_FULL_SEARCH_MOVES
                and not is_capture
                and move.promotion is None
                and not gives_check
                and not in_check
            ):
                # Log-based LMR reduction (adaptive)
                lmr_r = max(1, int(math.sqrt(depth - 1) * math.sqrt(moves_searched)))
                lmr_depth = max(1, depth - 1 - lmr_r)

                # Reduced-depth null-window search
                score = -self._negamax(board, lmr_depth, -alpha - 1, -alpha, ply + 1, orderer)

                # If LMR null-window beats alpha, re-search at full depth with null window
                if score > alpha:
                    score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, ply + 1, orderer)

                # If still beating alpha, do full window re-search (PVS re-search)
                if score > alpha:
                    score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1, orderer)

            elif moves_searched == 0:
                # First move: always full window at full depth
                score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1, orderer)
            else:
                # PVS: null window for non-LMR moves after the first
                score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, ply + 1, orderer)
                # Re-search with full window if null window beat alpha
                if score > alpha:
                    score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1, orderer)

            board.pop()
            moves_searched += 1

            if score > best_score:
                best_score = score
                best_move = move

            if score > alpha:
                alpha = score

            if alpha >= beta:
                # Beta cutoff — register killer / history for quiet moves
                if not is_capture:
                    orderer.update_killer(move, ply)
                    orderer.update_history(move, mover_color, depth)
                break

        # --- Store in TT ---
        if best_score <= original_alpha:
            flag = TT_UPPER
        elif best_score >= beta:
            flag = TT_LOWER
        else:
            flag = TT_EXACT
        self.tt.store(tt_key, TTEntry(depth, best_score, flag, best_move))

        return best_score

    # ------------------------------------------------------------------
    # Quiescence Search (fail-soft, with delta pruning)
    # ------------------------------------------------------------------

    def _quiescence(self, board: chess.Board, alpha: int, beta: int) -> int:
        """
        Extend search on captures/promotions/checks to avoid the horizon effect.
        Delta pruning: skip captures that can't possibly improve alpha.
        """
        self.nodes_searched += 1

        if board.is_game_over():
            return self._terminal_score(board, ply=0)

        # Stand-pat (lower bound: we can always choose not to capture)
        raw = evaluate(board)
        stand_pat = raw if board.turn == chess.WHITE else -raw

        if stand_pat >= beta:
            return stand_pat   # fail-soft
        if stand_pat > alpha:
            alpha = stand_pat

        best_score = stand_pat

        # Enumerate captures and promotions only
        capture_moves = [
            m for m in board.legal_moves
            if board.is_capture(m) or m.promotion is not None
        ]
        capture_moves.sort(key=lambda m: self._mvv_lva_score(board, m), reverse=True)

        for move in capture_moves:
            # SEE pruning: skip captures that lose material (e.g. queen takes pawn, pawn recaptures)
            if not move.promotion and see(board, move) < 0:
                continue

            # Delta pruning: skip if even capturing the best possible piece
            # won't bring the score up to alpha.
            if not move.promotion:
                victim = board.piece_at(move.to_square)
                if victim is not None:
                    from engine.evaluation import PIECE_VALUES
                    gain = PIECE_VALUES.get(victim.piece_type, 0)
                    if stand_pat + gain + DELTA_MARGIN <= alpha:
                        continue

            board.push(move)
            score = -self._quiescence(board, -beta, -alpha)
            board.pop()

            if score > best_score:
                best_score = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                return best_score  # fail-soft

        return best_score

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _terminal_score(self, board: chess.Board, ply: int) -> int:
        if board.is_checkmate():
            return -(MATE_SCORE - ply)
        return 0

    def _elapsed(self) -> float:
        return time.time() - self._start_time

    @staticmethod
    def _mvv_lva_score(board: chess.Board, move: chess.Move) -> int:
        from engine.evaluation import PIECE_VALUES
        attacker = board.piece_at(move.from_square)
        if attacker is None:
            return 0
        if board.is_en_passant(move):
            victim_val = PIECE_VALUES[chess.PAWN]
        else:
            victim = board.piece_at(move.to_square)
            victim_val = PIECE_VALUES.get(victim.piece_type, 0) if victim else 0
        return victim_val * 10 - PIECE_VALUES.get(attacker.piece_type, 0)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _count_major_pieces(board: chess.Board, color: chess.Color) -> int:
    """Count non-pawn, non-king pieces for the given side (for NMP guard)."""
    count = 0
    for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
        count += len(board.pieces(pt, color))
    return count
