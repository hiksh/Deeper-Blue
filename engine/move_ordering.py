"""
move_ordering.py

Move ordering heuristics to improve Alpha-Beta pruning efficiency.

The goal is to search the most promising moves first so that the alpha-beta
algorithm can prune more branches early.

Ordering priority (highest → lowest):
  1. PV move (from previous iteration's transposition table)
  2. Winning / equal captures  — MVV-LVA (Most Valuable Victim, Least Valuable Attacker)
  3. Killer moves              — quiet moves that caused a beta-cutoff at same depth
  4. History heuristic         — quiet moves ordered by historical beta-cutoff count
  5. Losing captures
  6. Other quiet moves
"""

import chess
from engine.evaluation import PIECE_VALUES

# Number of killer move slots per ply
MAX_KILLERS = 2
# Maximum search depth supported
MAX_DEPTH = 64


class MoveOrderer:
    """
    Maintains per-search state for move ordering heuristics
    (killer moves table, history heuristic table).

    Create one MoveOrderer per search (reset between searches).
    """

    def __init__(self) -> None:
        # killers[ply] = list of up to MAX_KILLERS quiet moves
        self.killers: list[list[chess.Move]] = [[] for _ in range(MAX_DEPTH)]
        # history[color][from_sq][to_sq] = accumulated score
        self.history: dict[chess.Color, list[list[int]]] = {
            chess.WHITE: [[0] * 64 for _ in range(64)],
            chess.BLACK: [[0] * 64 for _ in range(64)],
        }

    def update_killer(self, move: chess.Move, ply: int) -> None:
        """Register a quiet move that caused a beta-cutoff as a killer move."""
        if ply >= MAX_DEPTH:
            return
        slot = self.killers[ply]
        if move not in slot:
            slot.insert(0, move)
            if len(slot) > MAX_KILLERS:
                slot.pop()

    def update_history(self, move: chess.Move, color: chess.Color, depth: int) -> None:
        """Increase history score for a quiet move that caused a beta-cutoff."""
        self.history[color][move.from_square][move.to_square] += depth * depth

    def order_moves(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        ply: int,
        pv_move: chess.Move | None = None,
    ) -> list[chess.Move]:
        """
        Sort moves from best to worst (descending score).
        Higher score → searched earlier → more pruning.
        """
        scored: list[tuple[int, chess.Move]] = []
        for move in moves:
            scored.append((self._score_move(board, move, ply, pv_move), move))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _score_move(
        self,
        board: chess.Board,
        move: chess.Move,
        ply: int,
        pv_move: chess.Move | None,
    ) -> int:
        # 1. PV / hash move gets highest priority
        if move == pv_move:
            return 2_000_000

        is_capture = board.is_capture(move)

        if is_capture:
            return 1_000_000 + self._mvv_lva(board, move)

        # 2. Promotions (non-capture)
        if move.promotion is not None:
            return 900_000 + PIECE_VALUES.get(move.promotion, 0)

        # 3. Check-giving moves get a bonus (searched before quiet moves)
        if board.gives_check(move):
            return 850_000

        # 4. Killer moves
        if ply < MAX_DEPTH and move in self.killers[ply]:
            slot_idx = self.killers[ply].index(move)
            return 800_000 - slot_idx  # first killer > second killer

        # 5. History heuristic
        color = board.turn
        hist = self.history[color][move.from_square][move.to_square]
        return hist  # could be 0 for unseen moves

    @staticmethod
    def _mvv_lva(board: chess.Board, move: chess.Move) -> int:
        """
        MVV-LVA: Most Valuable Victim – Least Valuable Attacker.
        Score = victim_value * 10 - attacker_value
        En-passant captures are handled (victim is always a pawn).
        """
        attacker = board.piece_at(move.from_square)
        if attacker is None:
            return 0

        # En passant: victim is always a pawn
        if board.is_en_passant(move):
            victim_val = PIECE_VALUES[chess.PAWN]
        else:
            victim_piece = board.piece_at(move.to_square)
            victim_val = PIECE_VALUES.get(victim_piece.piece_type, 0) if victim_piece else 0

        attacker_val = PIECE_VALUES.get(attacker.piece_type, 0)
        return victim_val * 10 - attacker_val
