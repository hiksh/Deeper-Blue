"""
pgn_parser.py

Parses PGN files from the 1997 Kasparov vs Deep Blue match and extracts
positions relevant for comparison (middlegame and endgame only).

Game phase definitions
-----------------------
Opening  : move_number < 15
           (standard opening theory range; Deep Blue used an opening book
            for this phase, so algorithm comparison is not meaningful)
Middlegame: 15 <= move_number and piece_count > 6
           Rationale:
             - Move 15+ ensures both sides have developed and left book lines.
             - piece_count > 6 distinguishes from simplified endgames where
               tablebase-level accuracy is expected.
Endgame  : move_number >= 15 and piece_count <= 6
           (non-pawn, non-king pieces: Q, R, B, N)

piece_count = total Q + R + B + N on both sides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterator

import chess
import chess.pgn


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PositionRecord:
    """A single position extracted from a game for comparison."""
    game_id: str           # e.g. "game1"
    move_number: int       # full-move number (1-based)
    color: chess.Color     # side to move at this position
    fen: str               # FEN before the move is played
    deep_blue_move: str    # Deep Blue's actual move in UCI notation
    phase: str             # "middlegame" or "endgame"


@dataclass
class GameRecord:
    """All extracted positions from a single PGN game."""
    game_id: str
    white: str
    black: str
    result: str
    positions: list[PositionRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase classification
# ---------------------------------------------------------------------------

MIDGAME_START_MOVE = 15       # move number threshold for leaving opening
ENDGAME_PIECE_THRESHOLD = 6   # total non-pawn, non-king pieces


def _count_pieces(board: chess.Board) -> int:
    """Return total number of queens, rooks, bishops, and knights on the board."""
    count = 0
    for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
        count += len(board.pieces(pt, chess.WHITE))
        count += len(board.pieces(pt, chess.BLACK))
    return count


def classify_phase(board: chess.Board, move_number: int) -> str | None:
    """
    Returns "middlegame", "endgame", or None (opening — skip).
    """
    if move_number < MIDGAME_START_MOVE:
        return None  # opening
    piece_count = _count_pieces(board)
    return "endgame" if piece_count <= ENDGAME_PIECE_THRESHOLD else "middlegame"


# ---------------------------------------------------------------------------
# PGN parsing
# ---------------------------------------------------------------------------

def _deep_blue_color(game: chess.pgn.Game, filename: str) -> chess.Color:
    """
    Determine which color Deep Blue played in a given game.
    Tries PGN headers first, falls back to filename-based heuristics.
    """
    white = game.headers.get("White", "").lower()
    black = game.headers.get("Black", "").lower()
    if "deep blue" in white or "deepblue" in white:
        return chess.WHITE
    if "deep blue" in black or "deepblue" in black:
        return chess.BLACK
    # Fallback: odd games (1, 3, 5) Deep Blue played Black; even games White
    # (based on 1997 match schedule)
    try:
        game_num = int(os.path.splitext(os.path.basename(filename))[0].replace("game", ""))
        return chess.BLACK if game_num % 2 == 1 else chess.WHITE
    except ValueError:
        return chess.WHITE


def parse_pgn_file(filepath: str) -> GameRecord | None:
    """
    Parse a single PGN file and extract middlegame/endgame positions
    where Deep Blue made a move.

    Returns a GameRecord, or None if the file could not be parsed.
    """
    game_id = os.path.splitext(os.path.basename(filepath))[0]

    with open(filepath, encoding="utf-8", errors="replace") as f:
        game = chess.pgn.read_game(f)

    if game is None:
        return None

    db_color = _deep_blue_color(game, filepath)
    record = GameRecord(
        game_id=game_id,
        white=game.headers.get("White", "?"),
        black=game.headers.get("Black", "?"),
        result=game.headers.get("Result", "*"),
    )

    board = game.board()
    for node in game.mainline():
        move = node.move
        move_number = board.fullmove_number
        color = board.turn

        # Only record positions where Deep Blue moved
        if color == db_color:
            phase = classify_phase(board, move_number)
            if phase is not None:
                record.positions.append(
                    PositionRecord(
                        game_id=game_id,
                        move_number=move_number,
                        color=color,
                        fen=board.fen(),
                        deep_blue_move=move.uci(),
                        phase=phase,
                    )
                )

        board.push(move)

    return record


def parse_pgn_directory(directory: str) -> list[GameRecord]:
    """
    Parse all .pgn files in a directory and return extracted GameRecords.
    """
    records: list[GameRecord] = []
    if not os.path.isdir(directory):
        return records

    for filename in sorted(os.listdir(directory)):
        if not filename.lower().endswith(".pgn"):
            continue
        filepath = os.path.join(directory, filename)
        record = parse_pgn_file(filepath)
        if record is not None and record.positions:
            records.append(record)

    return records


def iter_positions(records: list[GameRecord]) -> Iterator[PositionRecord]:
    """Flatten all positions from multiple game records into a single iterator."""
    for record in records:
        yield from record.positions
