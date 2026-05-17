"""
tuning/data_loader.py

Download Lichess Elite games and extract quiet positions for Texel tuning.

Quiet position definition:
  - Not in check
  - No captures available
  - Move >= 10 (skip opening)

Usage:
    from tuning.data_loader import download_lichess_elite, extract_quiet_positions, save_positions, load_positions

    pgn_path = download_lichess_elite(2024, 1, dest_dir="data/")
    positions = extract_quiet_positions(pgn_path, max_positions=200_000)
    save_positions(positions, "data/positions.json.gz")

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
# Lichess Elite Database URL
# ---------------------------------------------------------------------------
_ELITE_URL = "https://database.lichess.org/elite/{year}-{month:02d}.pgn.zst"


def download_lichess_elite(
    year: int,
    month: int,
    dest_dir: str | Path = "data/",
) -> Path:
    """Download Lichess Elite PGN.zst for the given month and decompress to .pgn.

    Requires `zstandard` package for .zst decompression.
    If the decompressed .pgn already exists, skip the download.

    Returns path to the decompressed .pgn file.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    zst_name = f"lichess_elite_{year}-{month:02d}.pgn.zst"
    pgn_name = f"lichess_elite_{year}-{month:02d}.pgn"
    zst_path = dest_dir / zst_name
    pgn_path = dest_dir / pgn_name

    if pgn_path.exists():
        print(f"  Already exists: {pgn_path}")
        return pgn_path

    url = _ELITE_URL.format(year=year, month=month)
    print(f"  Downloading: {url}")
    print(f"  Destination: {zst_path}")

    try:
        _download_with_progress(url, zst_path)
    except Exception as exc:
        raise RuntimeError(f"Download failed: {exc}\n"
                           f"You can manually download from:\n  {url}") from exc

    print(f"  Decompressing to: {pgn_path}")
    _decompress_zst(zst_path, pgn_path)
    zst_path.unlink()  # remove compressed file to save space
    return pgn_path


def _download_with_progress(url: str, dest: Path) -> None:
    def reporthook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 / total_size)
            mb = downloaded / 1_048_576
            total_mb = total_size / 1_048_576
            print(f"\r  {pct:5.1f}%  {mb:.1f}/{total_mb:.1f} MB", end="", flush=True)
        else:
            print(f"\r  {downloaded / 1_048_576:.1f} MB", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook)
    print()  # newline


def _decompress_zst(src: Path, dest: Path) -> None:
    try:
        import zstandard
    except ImportError:
        raise ImportError(
            "zstandard is required to decompress .zst files.\n"
            "Install it with: pip install zstandard"
        )
    dctx = zstandard.ZstdDecompressor()
    with open(src, "rb") as ifh, open(dest, "wb") as ofh:
        dctx.copy_stream(ifh, ofh)


# ---------------------------------------------------------------------------
# Position extraction
# ---------------------------------------------------------------------------

def extract_quiet_positions(
    pgn_path: str | Path,
    max_positions: int = 200_000,
    min_elo: int = 2200,
    max_per_game: int = 5,
    skip_moves: int = 10,
    seed: int = 42,
) -> list[tuple[str, float]]:
    """Parse PGN, extract quiet positions with game results.

    Args:
        pgn_path:      Path to a .pgn file (plain text or gzip).
        max_positions: Maximum number of positions to collect.
        min_elo:       Minimum ELO for both players (filters out weak games).
        max_per_game:  Max positions sampled from a single game.
        skip_moves:    Ignore first N half-moves (skip opening).
        seed:          Random seed for reproducible sampling.

    Returns:
        List of (fen, result) where result ∈ {0.0, 0.5, 1.0} (White's perspective).
    """
    random.seed(seed)
    positions: list[tuple[str, float]] = []
    pgn_path = Path(pgn_path)

    opener = gzip.open if pgn_path.suffix == ".gz" else open
    open_kwargs = {"mode": "rt", "encoding": "utf-8", "errors": "ignore"}

    games_read = 0
    with opener(pgn_path, **open_kwargs) as f:
        while len(positions) < max_positions:
            game = chess.pgn.read_game(f)
            if game is None:
                break

            games_read += 1
            if games_read % 5000 == 0:
                print(f"\r  {games_read:,} games scanned, {len(positions):,} positions collected",
                      end="", flush=True)

            # Filter by ELO
            try:
                w_elo = int(game.headers.get("WhiteElo", "0") or "0")
                b_elo = int(game.headers.get("BlackElo", "0") or "0")
                if w_elo < min_elo or b_elo < min_elo:
                    continue
            except ValueError:
                continue

            # Parse result
            result_str = game.headers.get("Result", "*")
            if result_str == "1-0":
                result = 1.0
            elif result_str == "0-1":
                result = 0.0
            elif result_str == "1/2-1/2":
                result = 0.5
            else:
                continue

            # Walk through the game and collect candidate positions
            board = game.board()
            candidates: list[str] = []
            half_move = 0

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

            if not candidates:
                continue

            n = min(max_per_game, len(candidates))
            sampled = random.sample(candidates, n)
            positions.extend((fen, result) for fen in sampled)

    print(f"\r  {games_read:,} games scanned, {len(positions):,} positions collected")

    random.shuffle(positions)
    return positions[:max_positions]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_positions(positions: list[tuple[str, float]], path: str | Path) -> None:
    """Save positions as gzip-compressed JSON (list of [fen, result] pairs)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [[fen, result] for fen, result in positions]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    size_mb = path.stat().st_size / 1_048_576
    print(f"  Saved {len(positions):,} positions to {path} ({size_mb:.1f} MB)")


def load_positions(path: str | Path) -> list[tuple[str, float]]:
    """Load positions from gzip-compressed JSON."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    return [(row[0], float(row[1])) for row in data]
