"""
evaluation.py

Static board evaluation for the Deeper-Blue chess engine.

Components:
  - Piece material values
  - Piece-Square Tables (PST) for positional bonuses
  - Game phase detection (middlegame / endgame)
  - Mobility evaluation
  - King safety
  - Pawn structure (doubled, isolated, passed pawns)

All scores are returned from White's perspective in centipawns.
Call evaluate(board) for the final score; positive = White is better.
"""

import chess

# ---------------------------------------------------------------------------
# Material values (centipawns)
# ---------------------------------------------------------------------------
PIECE_VALUES = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   20000,
}

# ---------------------------------------------------------------------------
# Piece-Square Tables (PST)
# White's perspective; index 0 = a1, index 63 = h8.
# These tables encode positional preferences per piece type.
# ---------------------------------------------------------------------------

# fmt: off
PST_PAWN_MG = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]

PST_PAWN_EG = [
     0,  0,  0,  0,  0,  0,  0,  0,
    80, 80, 80, 80, 80, 80, 80, 80,
    50, 50, 50, 50, 50, 50, 50, 50,
    30, 30, 30, 30, 30, 30, 30, 30,
    20, 20, 20, 20, 20, 20, 20, 20,
    10, 10, 10, 10, 10, 10, 10, 10,
     5,  5,  5,  5,  5,  5,  5,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]

PST_KNIGHT = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]

PST_BISHOP = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]

PST_ROOK_MG = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
]

PST_QUEEN_MG = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]

PST_KING_MG = [
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
]

PST_KING_EG = [
    -50,-40,-30,-20,-20,-30,-40,-50,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
]
# fmt: on

# PST lookup: piece_type -> (mg_table, eg_table)
# If a piece has only one table, it's used for both phases.
_PST = {
    chess.PAWN:   (PST_PAWN_MG,   PST_PAWN_EG),
    chess.KNIGHT: (PST_KNIGHT,     PST_KNIGHT),
    chess.BISHOP: (PST_BISHOP,     PST_BISHOP),
    chess.ROOK:   (PST_ROOK_MG,   PST_ROOK_MG),
    chess.QUEEN:  (PST_QUEEN_MG,  PST_QUEEN_MG),
    chess.KING:   (PST_KING_MG,   PST_KING_EG),
}


def _pst_score(piece_type: int, square: int, color: chess.Color, phase: float) -> int:
    """
    Return the PST bonus for a piece on a given square.
    phase: 0.0 = pure middlegame, 1.0 = pure endgame (tapered eval).
    PST tables are stored from White's a1=0 perspective.
    For Black we mirror vertically (flip rank).
    """
    mg_table, eg_table = _PST[piece_type]
    # Mirror square for Black (flip rank)
    idx = square if color == chess.WHITE else chess.square_mirror(square)
    mg = mg_table[idx]
    eg = eg_table[idx]
    return round(mg * (1 - phase) + eg * phase)


# ---------------------------------------------------------------------------
# Game phase detection
# ---------------------------------------------------------------------------
PHASE_WEIGHTS = {
    chess.PAWN:   0,
    chess.KNIGHT: 1,
    chess.BISHOP: 1,
    chess.ROOK:   2,
    chess.QUEEN:  4,
    chess.KING:   0,
}
TOTAL_PHASE = 16 * 0 + 4 * 1 + 4 * 1 + 4 * 2 + 2 * 4  # = 24


def get_phase(board: chess.Board) -> float:
    """
    Returns a value in [0.0, 1.0].
    0.0 = opening/middlegame (all pieces on board)
    1.0 = endgame (very few pieces)
    """
    phase = 0
    for piece_type in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
        phase += len(board.pieces(piece_type, chess.WHITE)) * PHASE_WEIGHTS[piece_type]
        phase += len(board.pieces(piece_type, chess.BLACK)) * PHASE_WEIGHTS[piece_type]
    # Clamp and normalize: more pieces = closer to 0 (middlegame)
    phase = min(phase, TOTAL_PHASE)
    return 1.0 - (phase / TOTAL_PHASE)


# ---------------------------------------------------------------------------
# Pawn structure
# ---------------------------------------------------------------------------

def _pawn_structure_score(board: chess.Board, color: chess.Color) -> int:
    """
    Penalizes:
      - Doubled pawns   (-20 per extra pawn on the same file)
      - Isolated pawns  (-30: no friendly pawn on adjacent files)
    Rewards:
      - Passed pawns    (+50 to +200 depending on rank)
    """
    score = 0
    pawns = board.pieces(chess.PAWN, color)
    opp_pawns = board.pieces(chess.PAWN, not color)

    pawn_files = [chess.square_file(sq) for sq in pawns]
    opp_pawn_files = set(chess.square_file(sq) for sq in opp_pawns)

    for sq in pawns:
        f = chess.square_file(sq)
        r = chess.square_rank(sq)

        # Doubled pawns
        if pawn_files.count(f) > 1:
            score -= 20

        # Isolated pawns
        adjacent_files = {f - 1, f + 1} & set(range(8))
        if not any(af in pawn_files for af in adjacent_files):
            score -= 30

        # Passed pawns: no opponent pawns on same or adjacent files ahead
        if color == chess.WHITE:
            ahead_ranks = range(r + 1, 8)
        else:
            ahead_ranks = range(0, r)
        blocking_files = {f - 1, f, f + 1} & set(range(8))
        is_passed = not any(
            chess.square_file(opp_sq) in blocking_files
            and chess.square_rank(opp_sq) in ahead_ranks
            for opp_sq in opp_pawns
        )
        if is_passed:
            # Bonus increases as pawn advances toward promotion
            advance = r if color == chess.WHITE else (7 - r)
            score += [0, 10, 20, 40, 60, 80, 120, 0][advance]

    return score


# ---------------------------------------------------------------------------
# King safety
# ---------------------------------------------------------------------------

def _king_safety_score(board: chess.Board, color: chess.Color, phase: float) -> int:
    """
    In middlegame: reward pawn shield near king, penalize open files near king.
    In endgame: king activity (proximity to center) is rewarded.
    """
    king_sq = board.king(color)
    if king_sq is None:
        return 0

    score = 0
    mg_weight = 1.0 - phase

    # Pawn shield (middlegame only)
    if mg_weight > 0.2:
        shield_squares = board.attacks(king_sq)
        for sq in shield_squares:
            if board.piece_at(sq) == chess.Piece(chess.PAWN, color):
                score += round(10 * mg_weight)

    # Open file penalty near king (middlegame)
    king_file = chess.square_file(king_sq)
    for df in (-1, 0, 1):
        f = king_file + df
        if 0 <= f <= 7:
            file_pawns = [
                sq for sq in board.pieces(chess.PAWN, color)
                if chess.square_file(sq) == f
            ]
            if not file_pawns:
                score -= round(15 * mg_weight)

    # Endgame king centralization bonus
    if phase > 0.4:
        king_rank = chess.square_rank(king_sq)
        center_dist = abs(3.5 - king_file) + abs(3.5 - king_rank)
        score += round((7 - center_dist) * 5 * phase)

    return score


# ---------------------------------------------------------------------------
# Mobility
# ---------------------------------------------------------------------------

def _mobility_score(board: chess.Board, color: chess.Color) -> int:
    """
    Count squares attacked by each non-pawn, non-king piece,
    excluding squares occupied by own pieces.
    +2 centipawns per available square.
    """
    own_pieces = board.occupied_co[color]
    score = 0
    for piece_type in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
        for sq in board.pieces(piece_type, color):
            attacks = board.attacks(sq)
            # Exclude squares occupied by own pieces
            available = attacks & ~chess.SquareSet(own_pieces)
            score += len(available) * 2
    return score


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate(board: chess.Board) -> int:
    """
    Static evaluation of the board position.
    Returns centipawns from White's perspective.
    Positive  → White is better.
    Negative  → Black is better.
    """
    if board.is_checkmate():
        # The side to move is in checkmate (they lost)
        return -30000 if board.turn == chess.WHITE else 30000

    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.is_fifty_moves()
        or board.is_repetition(2)
    ):
        return 0

    phase = get_phase(board)
    score = 0

    for color in [chess.WHITE, chess.BLACK]:
        sign = 1 if color == chess.WHITE else -1
        side_score = 0

        # Material + PST
        for piece_type in PIECE_VALUES:
            for sq in board.pieces(piece_type, color):
                side_score += PIECE_VALUES[piece_type]
                side_score += _pst_score(piece_type, sq, color, phase)

        # Structural / positional bonuses
        side_score += _pawn_structure_score(board, color)
        side_score += _king_safety_score(board, color, phase)
        side_score += _mobility_score(board, color)

        score += sign * side_score

    return score
