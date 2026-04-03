"""
evaluation.py

Static board evaluation for the Deeper-Blue chess engine.

Components:
  - Piece material values
  - Piece-Square Tables (PST) for positional bonuses
  - Game phase detection (middlegame / endgame) with tapered evaluation
  - Mobility evaluation
  - King safety (pawn shield, open files near king)
  - Pawn structure (doubled, isolated, backward, passed pawns)
  - Bishop pair bonus
  - Rook on open / semi-open file bonus
  - Rook on 7th rank bonus

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

# Bonus for having the bishop pair (both light- and dark-squared bishops)
BISHOP_PAIR_BONUS = 50

# Rook file bonuses (centipawns)
ROOK_OPEN_FILE_BONUS      = 25   # no pawns on the file
ROOK_SEMI_OPEN_FILE_BONUS = 12   # only opponent pawns on the file

# Rook on 7th rank (or 2nd for Black) — attacking pawns on their home rank
ROOK_ON_7TH_BONUS = 25

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
      - Backward pawns  (-20: can't advance safely, no support behind)
    Rewards:
      - Passed pawns    (+10 to +120 depending on rank)
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
        friendly_adjacent = any(af in pawn_files for af in adjacent_files)
        if not friendly_adjacent:
            score -= 30

        # Backward pawns:
        # A pawn is backward if it cannot advance safely and no friendly pawn
        # supports it from behind on adjacent files.
        if color == chess.WHITE:
            advance_rank = r + 1
            behind_ranks = range(0, r)
        else:
            advance_rank = r - 1
            behind_ranks = range(r + 1, 8)

        if 0 <= advance_rank <= 7:
            advance_sq = chess.square(f, advance_rank)
            # Check if advance square is attacked by an opponent pawn
            opp_attacks_advance = any(
                chess.square_file(opp_sq) in adjacent_files
                and chess.square_rank(opp_sq) == (advance_rank + (1 if color == chess.WHITE else -1))
                for opp_sq in opp_pawns
                if 0 <= chess.square_rank(opp_sq) <= 7
            )
            if opp_attacks_advance and not friendly_adjacent:
                # No adjacent friendly pawns to support its advance
                has_support_behind = any(
                    chess.square_file(p) in adjacent_files
                    and chess.square_rank(p) in behind_ranks
                    for p in pawns
                    if p != sq
                )
                if not has_support_behind:
                    score -= 20

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
            advance = r if color == chess.WHITE else (7 - r)
            score += [0, 10, 20, 40, 60, 80, 120, 0][advance]

    return score


# ---------------------------------------------------------------------------
# Bishop pair bonus
# ---------------------------------------------------------------------------

def _bishop_pair_score(board: chess.Board, color: chess.Color) -> int:
    """
    Award a bonus when a side has both the light- and dark-squared bishops.
    The bishop pair coordinates well in open positions and is worth ~50cp.
    """
    bishops = list(board.pieces(chess.BISHOP, color))
    if len(bishops) >= 2:
        # Check that we have bishops on both light and dark squares
        # Light square: (file + rank) % 2 == 1; dark: (file + rank) % 2 == 0
        light = any((chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1 for sq in bishops)
        dark  = any((chess.square_file(sq) + chess.square_rank(sq)) % 2 == 0 for sq in bishops)
        if light and dark:
            return BISHOP_PAIR_BONUS
    return 0


# ---------------------------------------------------------------------------
# Rook bonuses
# ---------------------------------------------------------------------------

def _rook_bonus_score(board: chess.Board, color: chess.Color) -> int:
    """
    Bonuses for rooks on:
      - Open files  (no pawns of either color): +25cp per rook
      - Semi-open files (no own pawns, but opponent has one): +12cp per rook
      - 7th rank (2nd rank for Black): attacking opponent's pawns: +25cp per rook
    """
    score = 0
    own_pawns   = board.pieces(chess.PAWN, color)
    opp_pawns   = board.pieces(chess.PAWN, not color)
    own_pawn_files = {chess.square_file(sq) for sq in own_pawns}
    opp_pawn_files = {chess.square_file(sq) for sq in opp_pawns}

    seventh_rank = 6 if color == chess.WHITE else 1  # rank index 0..7

    for sq in board.pieces(chess.ROOK, color):
        f = chess.square_file(sq)
        r = chess.square_rank(sq)

        # Rook on 7th rank
        if r == seventh_rank:
            score += ROOK_ON_7TH_BONUS

        # Open / semi-open file
        if f not in own_pawn_files:
            if f not in opp_pawn_files:
                score += ROOK_OPEN_FILE_BONUS       # fully open
            else:
                score += ROOK_SEMI_OPEN_FILE_BONUS  # semi-open

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

    Components (per side):
      Material + PST (tapered MG/EG)
      Pawn structure (doubled, isolated, backward, passed)
      Bishop pair bonus
      Rook on open/semi-open file, 7th rank
      King safety (pawn shield, open files, endgame centralization)
      Mobility (attack squares for non-pawn, non-king pieces)
    """
    if board.is_checkmate():
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
        side_score += _bishop_pair_score(board, color)
        side_score += _rook_bonus_score(board, color)
        side_score += _king_safety_score(board, color, phase)
        side_score += _mobility_score(board, color)

        score += sign * side_score

    return score
