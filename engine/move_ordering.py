"""
move_ordering.py

Move ordering heuristics to improve Alpha-Beta pruning efficiency.

The goal is to search the most promising moves first so that the alpha-beta
algorithm can prune more branches early.

Ordering priority (highest → lowest):
  1. PV move (from previous iteration's transposition table)
  2. Winning captures (SEE > 0)  — ordered by SEE value
  3. Equal captures   (SEE == 0)
  4. Promotions (non-capture)
  5. Check-giving moves
  6. Killer moves
  7. History heuristic
  8. Losing captures  (SEE < 0)  — tried last
"""

import chess
from engine.evaluation import PIECE_VALUES

# ---------------------------------------------------------------------------
# Static Exchange Evaluation (SEE)
# ---------------------------------------------------------------------------

def _find_lva_move(board: chess.Board, to_sq: int) -> chess.Move | None:
    """Return the legal capture move to to_sq by the least valuable piece."""
    min_val = float("inf")
    best: chess.Move | None = None
    for move in board.legal_moves:
        if move.to_square != to_sq:
            continue
        piece = board.piece_at(move.from_square)
        if piece is None:
            continue
        val = PIECE_VALUES.get(piece.piece_type, float("inf"))
        if val < min_val:
            min_val = val
            best = move
    return best


def see(board: chess.Board, move: chess.Move) -> int:
    """
    Static Exchange Evaluation.

    Returns the expected centipawn gain/loss of the capture sequence starting
    with `move`.  Positive = good for the side making the move.

    Each side can choose not to recapture (simulated by clamping gain to 0
    at each step in the backpropagation pass).

    Algorithm:
      gain[0] = value of piece captured by the initial move
      gain[d] = value of piece on the square after d-1 recaptures
      Backtrack: gain[i] = max(gain[i] - gain[i+1], 0)  (right to left)
    """
    to_sq = move.to_square

    if board.is_en_passant(move):
        return 0   # pawn-for-pawn, treat as equal

    target = board.piece_at(to_sq)
    if target is None:
        return 0   # not a capture

    gain: list[int] = [PIECE_VALUES.get(target.piece_type, 0)]

    b = board.copy()
    b.push(move)

    for _ in range(16):   # max exchange depth
        lva = _find_lva_move(b, to_sq)
        if lva is None:
            break
        on_sq = b.piece_at(to_sq)
        if on_sq is None:
            break
        gain.append(PIECE_VALUES.get(on_sq.piece_type, 0))
        b.push(lva)

    # Backpropagate: each side can decline to recapture if it would be negative
    for i in range(len(gain) - 2, -1, -1):
        gain[i] = max(gain[i] - gain[i + 1], 0)

    return gain[0]

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
            see_val = see(board, move)
            if see_val > 0:
                # Winning capture: above quiet moves, ordered by SEE value
                return 1_100_000 + see_val
            elif see_val == 0:
                # Equal capture: just below winning captures
                return 1_000_000
            else:
                # Losing capture: searched last, still ordered by SEE
                return 200_000 + see_val  # can be negative, that's fine

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
