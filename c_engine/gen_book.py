"""
gen_book.py
Generates book.bin (Polyglot format) by BFS-exploring common opening
positions up to a given depth, using Stockfish for move selection.

Usage:
    python gen_book.py [stockfish_path]
"""
import sys, struct, os
import chess
import chess.engine
import chess.polyglot

STOCKFISH = sys.argv[1] if len(sys.argv) > 1 else \
    os.path.join(os.path.dirname(__file__), "..", "stockfish",
                 "stockfish-windows-x86-64-avx2.exe")
OUT = os.path.join(os.path.dirname(__file__), "book.bin")

MULTIPV  = 3    # top N moves per position
SF_DEPTH = 18   # Stockfish analysis depth
MAX_PLY  = 12   # explore opening up to this ply (half-moves)
MIN_MATE_DIFF = 50  # centipawn threshold to include a move


def encode_move(move: chess.Move) -> int:
    ff = chess.square_file(move.from_square)
    fr = chess.square_rank(move.from_square)
    tf = chess.square_file(move.to_square)
    tr = chess.square_rank(move.to_square)
    promo = 0
    if move.promotion:
        promo = {chess.KNIGHT: 1, chess.BISHOP: 2,
                 chess.ROOK: 3,   chess.QUEEN: 4}[move.promotion]
    return tf | (tr << 3) | (ff << 6) | (fr << 9) | (promo << 12)


# key -> list of (encoded_move, weight)
book: dict[int, list[tuple[int, int]]] = {}


def add_entry(board: chess.Board, move: chess.Move, weight: int) -> None:
    key = chess.polyglot.zobrist_hash(board)
    em  = encode_move(move)
    if key not in book:
        book[key] = []
    # Avoid duplicate moves for same position
    for i, (m, _) in enumerate(book[key]):
        if m == em:
            if weight > book[key][i][1]:
                book[key][i] = (em, weight)
            return
    book[key].append((em, weight))


print(f"Stockfish: {STOCKFISH}")
print(f"Generating book (depth={SF_DEPTH}, ply≤{MAX_PLY}, multipv={MULTIPV})...")

with chess.engine.SimpleEngine.popen_uci(STOCKFISH) as engine:
    queue: list[chess.Board] = [chess.Board()]
    visited: set[int] = set()
    processed = 0

    while queue:
        board = queue.pop(0)
        if board.is_game_over():
            continue
        # Only explore opening phase
        if len(board.move_stack) >= MAX_PLY:
            continue
        key = chess.polyglot.zobrist_hash(board)
        if key in visited:
            continue
        visited.add(key)
        processed += 1

        infos = engine.analyse(
            board,
            chess.engine.Limit(depth=SF_DEPTH),
            multipv=MULTIPV,
        )

        # Find best score (for relative weighting)
        best_score = None
        for info in infos:
            if "score" not in info or "pv" not in info or not info["pv"]:
                continue
            sc = info["score"].white().score(mate_score=30000)
            if best_score is None:
                best_score = sc

        if best_score is None:
            continue

        for rank, info in enumerate(infos):
            if "score" not in info or "pv" not in info or not info["pv"]:
                continue
            move = info["pv"][0]
            sc   = info["score"].white().score(mate_score=30000)
            # Weight: best move = 1000, others proportionally less
            diff = abs((best_score or 0) - sc)
            if diff > 200:  # more than 2 pawns worse → skip
                break
            weight = max(100, 1000 - rank * 300)
            add_entry(board, move, weight)

            child = board.copy()
            child.push(move)
            queue.append(child)

        if processed % 50 == 0:
            print(f"  {processed} positions processed, {len(book)} book entries...")

total_entries = sum(len(v) for v in book.values())
print(f"\nTotal positions: {len(book)}, total move entries: {total_entries}")

# Write Polyglot binary: sorted by key, each entry 16 bytes big-endian
all_entries: list[tuple[int, int, int]] = []
for key, moves in book.items():
    for (em, weight) in moves:
        all_entries.append((key, em, weight))
all_entries.sort(key=lambda x: x[0])

with open(OUT, "wb") as f:
    for (key, em, weight) in all_entries:
        f.write(struct.pack(">QHHI", key, em, weight, 0))

print(f"Written {len(all_entries)} entries → {OUT}")
