"""
tuning/data_loader.py

Stream Lichess database games and extract quiet positions for Texel tuning.

URL formats (confirmed working):
  Standard: https://database.lichess.org/standard/lichess_db_standard_rated_{year}-{month:02d}.pgn.zst
  (Streams directly — downloads only until max_positions reached, not the full file.)

Quiet position:
  - Not in check
  - No captures available in the position
  - Move >= skip_moves half-moves (skip opening)

Usage:
    # Stream from Lichess and extract 200K positions
    python main.py download-positions --year 2024 --month 1 --n 200000

    # Use a local PGN file you already have
    python main.py download-positions --pgn /path/to/games.pgn --n 200000

    # Load saved positions
    from tuning.data_loader import load_positions
    positions = load_positions("data/positions.json.gz")
"""

from __future__ import annotations

import gzip
import io
import json
import os
import random
import sys
import urllib.request
from pathlib import Path

import chess
import chess.pgn

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_STANDARD_URL = (
    "https://database.lichess.org/standard/"
    "lichess_db_standard_rated_{year}-{month:02d}.pgn.zst"
)


def build_url(year: int, month: int) -> str:
    return _STANDARD_URL.format(year=year, month=month)


# ---------------------------------------------------------------------------
# Streaming extraction (no full-file download needed)
# ---------------------------------------------------------------------------

def stream_extract_positions(
    url: str,
    max_positions: int = 200_000,
    min_elo: int = 2200,
    max_per_game: int = 5,
    skip_moves: int = 10,
    seed: int = 42,
) -> list[tuple[str, float]]:
    """Stream a Lichess .pgn.zst URL and extract quiet positions.

    Stops streaming as soon as max_positions are collected — avoids
    downloading the entire file (which can be 20+ GB).

    Args:
        url:           Full URL to a .pgn.zst file.
        max_positions: Stop after this many positions.
        min_elo:       Skip games where either player is below this ELO.
        max_per_game:  Max positions sampled from one game.
        skip_moves:    Skip the first N half-moves (opening).
        seed:          RNG seed for reproducibility.

    Returns:
        List of (fen, result) where result ∈ {0.0, 0.5, 1.0} (White's perspective).
    """
    try:
        import zstandard
    except ImportError:
        raise ImportError(
            "zstandard is required.  Install with: pip install zstandard"
        )

    random.seed(seed)
    positions: list[tuple[str, float]] = []
    games_read = 0

    print(f"  Streaming: {url}")
    print(f"  Will stop after {max_positions:,} positions (no full download needed)\n")

    with urllib.request.urlopen(url, timeout=30) as response:
        dctx  = zstandard.ZstdDecompressor()
        reader = dctx.stream_reader(response)
        text  = io.TextIOWrapper(reader, encoding="utf-8", errors="ignore")

        while len(positions) < max_positions:
            try:
                game = chess.pgn.read_game(text)
            except Exception:
                continue
            if game is None:
                break

            games_read += 1
            if games_read % 2000 == 0:
                print(
                    f"\r  {games_read:,} games | {len(positions):,} / {max_positions:,} positions",
                    end="", flush=True,
                )

            # ELO filter
            try:
                w_elo = int(game.headers.get("WhiteElo", "0") or "0")
                b_elo = int(game.headers.get("BlackElo", "0") or "0")
                if w_elo < min_elo or b_elo < min_elo:
                    continue
            except ValueError:
                continue

            # Result
            result_str = game.headers.get("Result", "*")
            if result_str == "1-0":
                result = 1.0
            elif result_str == "0-1":
                result = 0.0
            elif result_str == "1/2-1/2":
                result = 0.5
            else:
                continue

            # Walk the game
            board      = game.board()
            candidates: list[str] = []
            half_move  = 0

            for move in game.mainline_moves():
                board.push(move)
                half_move += 1

                if half_move < skip_moves:
                    continue
                if board.is_check():
                    continue
                if any(board.is_capture(m) for m in board.legal_moves):
                    continue

                candidates.append(board.fen())

            if candidates:
                n       = min(max_per_game, len(candidates))
                sampled = random.sample(candidates, n)
                positions.extend((fen, result) for fen in sampled)

    print(
        f"\r  {games_read:,} games scanned | {len(positions):,} positions collected"
    )
    random.shuffle(positions)
    return positions[:max_positions]


# ---------------------------------------------------------------------------
# Local PGN file extraction (plain text or gzip)
# ---------------------------------------------------------------------------

def extract_from_pgn(
    pgn_path: str | Path,
    max_positions: int = 200_000,
    min_elo: int = 2200,
    max_per_game: int = 5,
    skip_moves: int = 10,
    seed: int = 42,
) -> list[tuple[str, float]]:
    """Extract quiet positions from a local .pgn or .pgn.gz file."""
    random.seed(seed)
    positions: list[tuple[str, float]] = []
    pgn_path = Path(pgn_path)
    games_read = 0

    opener    = gzip.open if pgn_path.suffix == ".gz" else open
    open_kw   = {"mode": "rt", "encoding": "utf-8", "errors": "ignore"}

    with opener(pgn_path, **open_kw) as f:
        while len(positions) < max_positions:
            try:
                game = chess.pgn.read_game(f)
            except Exception:
                continue
            if game is None:
                break

            games_read += 1
            if games_read % 2000 == 0:
                print(
                    f"\r  {games_read:,} games | {len(positions):,} / {max_positions:,} positions",
                    end="", flush=True,
                )

            try:
                w_elo = int(game.headers.get("WhiteElo", "0") or "0")
                b_elo = int(game.headers.get("BlackElo", "0") or "0")
                if w_elo < min_elo or b_elo < min_elo:
                    continue
            except ValueError:
                continue

            result_str = game.headers.get("Result", "*")
            if result_str == "1-0":
                result = 1.0
            elif result_str == "0-1":
                result = 0.0
            elif result_str == "1/2-1/2":
                result = 0.5
            else:
                continue

            board      = game.board()
            candidates: list[str] = []
            half_move  = 0

            for move in game.mainline_moves():
                board.push(move)
                half_move += 1

                if half_move < skip_moves:
                    continue
                if board.is_check():
                    continue
                if any(board.is_capture(m) for m in board.legal_moves):
                    continue

                candidates.append(board.fen())

            if candidates:
                n       = min(max_per_game, len(candidates))
                sampled = random.sample(candidates, n)
                positions.extend((fen, result) for fen in sampled)

    print(f"\r  {games_read:,} games | {len(positions):,} positions collected")
    random.shuffle(positions)
    return positions[:max_positions]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_positions(positions: list[tuple[str, float]], path: str | Path) -> None:
    """Save as gzip-compressed JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump([[fen, result] for fen, result in positions], f)
    size_mb = path.stat().st_size / 1_048_576
    print(f"  Saved {len(positions):,} positions → {path}  ({size_mb:.1f} MB)")


def load_positions(path: str | Path) -> list[tuple[str, float]]:
    """Load from gzip-compressed JSON."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    return [(row[0], float(row[1])) for row in data]
