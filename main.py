"""
main.py

Entry point for the Deeper-Blue chess engine comparison tool.

Modes
-----
1. compare   : Load Deep Blue PGN files, run comparison, print report.
2. visualize : Load comparison CSV and render charts (or run compare + visualize).
3. analyze   : Given a single FEN, show our engine's best move and Stockfish evaluation.
4. play      : Interactive: enter FEN, our engine replies with its best move.

Usage examples
--------------
  python main.py compare
  python main.py compare --pgn data/pgn/ --depth 5 --verbose --output results.csv
  python main.py visualize --csv results.csv --charts output/
  python main.py visualize --csv results.csv          # display in window
  python main.py compare --pgn data/pgn/ --charts output/   # compare + visualize in one step
  python main.py analyze --fen "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
  python main.py play
"""

import argparse
import os
import sys

import chess

from analysis.pgn_parser import parse_pgn_directory
from analysis.comparator import Comparator, ComparisonReport, MoveComparison, find_stockfish
from analysis.visualizer import plot_all
from analysis.engine_match import EngineMatch
from engine.minimax import SearchEngine
from engine.evaluation import EvalParams


# ---------------------------------------------------------------------------
# Sub-command: compare
# ---------------------------------------------------------------------------

def cmd_compare(args: argparse.Namespace) -> None:
    pgn_dir = args.pgn
    if not os.path.isdir(pgn_dir):
        print(f"[ERROR] PGN directory not found: {pgn_dir}")
        print("  Place Deep Blue 1997 PGN files in data/pgn/ and try again.")
        sys.exit(1)

    print(f"Loading PGN files from: {pgn_dir}")
    records = parse_pgn_directory(pgn_dir)

    if not records:
        print("[ERROR] No valid PGN files found in the directory.")
        sys.exit(1)

    total_positions = sum(len(r.positions) for r in records)
    print(f"  Loaded {len(records)} game(s), {total_positions} positions to compare.\n")

    try:
        sf_path = find_stockfish(args.stockfish)
        print(f"Using Stockfish: {sf_path}\n")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    comparator = Comparator(
        stockfish_path=sf_path,
        engine_depth=args.depth,
        engine_time=args.time,
    )

    print("Running comparison... (this may take a while)\n")
    report = comparator.compare_game_records(records, verbose=args.verbose)

    print(report.summary())

    # Optionally save detailed results to CSV
    if args.output:
        _save_csv(report, args.output)
        print(f"\nDetailed results saved to: {args.output}")

    # Optionally generate charts right after comparison
    if hasattr(args, "charts") and args.charts is not None:
        print(f"\nGenerating charts → {args.charts}")
        plot_all(report, output_dir=args.charts)
    elif hasattr(args, "charts") and args.charts == "":
        print("\nDisplaying charts...")
        plot_all(report, output_dir=None)


def _save_csv(report, filepath: str) -> None:
    import csv
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "game_id", "move_number", "phase",
            "our_move", "deep_blue_move",
            "our_score_cp", "deep_blue_score_cp", "delta_cp", "winner",
        ])
        for c in report.comparisons:
            writer.writerow([
                c.game_id, c.move_number, c.phase,
                c.our_move, c.deep_blue_move,
                c.our_score, c.deep_blue_score, c.delta, c.winner,
            ])


# ---------------------------------------------------------------------------
# Sub-command: visualize
# ---------------------------------------------------------------------------

def cmd_visualize(args: argparse.Namespace) -> None:
    """Load a saved CSV and render all charts."""
    import csv

    if not os.path.isfile(args.csv):
        print(f"[ERROR] CSV file not found: {args.csv}")
        print("  Run 'python main.py compare --output results.csv' first.")
        sys.exit(1)

    report = ComparisonReport()
    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            report.comparisons.append(MoveComparison(
                game_id=row["game_id"],
                move_number=int(row["move_number"]),
                phase=row["phase"],
                fen="",   # not needed for visualization
                our_move=row["our_move"],
                deep_blue_move=row["deep_blue_move"],
                our_score=int(row["our_score_cp"]),
                deep_blue_score=int(row["deep_blue_score_cp"]),
                delta=int(row["delta_cp"]),
                winner=row["winner"],
            ))

    if not report.comparisons:
        print("[ERROR] CSV is empty or invalid.")
        sys.exit(1)

    print(report.summary())
    output_dir = args.charts if args.charts else None
    if output_dir:
        print(f"Saving charts to: {output_dir}")
    else:
        print("Displaying charts in window...")
    plot_all(report, output_dir=output_dir)


# ---------------------------------------------------------------------------
# Sub-command: analyze
# ---------------------------------------------------------------------------

def cmd_analyze(args: argparse.Namespace) -> None:
    try:
        board = chess.Board(args.fen)
    except ValueError as e:
        print(f"[ERROR] Invalid FEN: {e}")
        sys.exit(1)

    print(f"Position:\n{board}\n")
    print(f"FEN: {args.fen}")
    print(f"Side to move: {'White' if board.turn == chess.WHITE else 'Black'}\n")

    engine = SearchEngine()
    print(f"Searching (depth={args.depth}, time_limit={args.time}s)...")
    move, score = engine.search(board, max_depth=args.depth, time_limit=args.time)

    if move is None:
        print("No legal moves available.")
        return

    print(f"  Best move   : {move.uci()} ({board.san(move)})")
    print(f"  Engine score: {score:+d} cp (from {'White' if board.turn == chess.WHITE else 'Black'}'s perspective)\n")

    # Stockfish evaluation for reference
    try:
        sf_path = find_stockfish(args.stockfish)
        import chess.engine
        with chess.engine.SimpleEngine.popen_uci(sf_path) as sf:
            b = board.copy()
            b.push(move)
            info = sf.analyse(b, chess.engine.Limit(time=0.5))
            sf_score = info["score"].white().score(mate_score=30000)
            if board.turn == chess.BLACK and sf_score is not None:
                sf_score = -sf_score
            print(f"  Stockfish eval after our move: {sf_score:+d} cp")
    except FileNotFoundError:
        print("  (Stockfish not available for reference evaluation)")


# ---------------------------------------------------------------------------
# Sub-command: play-human (pygame GUI)
# ---------------------------------------------------------------------------

def cmd_play_human(args: argparse.Namespace) -> None:
    import chess
    from game.chess_gui import launch
    player_color = chess.WHITE if args.color == "white" else chess.BLACK
    launch(player_color=player_color, engine_depth=args.depth, engine_time=args.time)


# ---------------------------------------------------------------------------
# Sub-command: match
# ---------------------------------------------------------------------------

def cmd_match(args: argparse.Namespace) -> None:
    """Play a match against an external UCI engine and report W/D/L."""
    import os
    if not os.path.isfile(args.opponent):
        print(f"[ERROR] Opponent engine not found: {args.opponent}")
        print("  Download Crafty: http://craftychess.com/")
        print("  Or use Stockfish with --elo to simulate era-appropriate strength:")
        print("    python main.py match --opponent stockfish/stockfish.exe --elo 2200")
        sys.exit(1)

    elo_str = f" (ELO {args.elo})" if args.elo else " (full strength)"
    print(f"Opponent : {args.opponent}{elo_str}")
    print(f"Games    : {args.games}  |  Depth: {args.depth}  |  Time/move: {args.time}s\n")

    match = EngineMatch(
        opponent_path=args.opponent,
        n_games=args.games,
        time_per_move=args.time,
        depth=args.depth,
        opponent_elo=args.elo,
    )

    result = match.play_match(verbose=True)
    print()
    print(result.summary())

    if args.output:
        _save_match_csv(result, args.output)
        print(f"\nGame results saved to: {args.output}")


def _save_match_csv(result, filepath: str) -> None:
    import csv
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["game", "our_color", "result", "termination", "half_moves"])
        for g in result.game_results:
            writer.writerow([
                g.game_number,
                "white" if g.our_color else "black",
                g.result,
                g.termination,
                g.half_moves,
            ])


# ---------------------------------------------------------------------------
# Sub-command: play (CLI fallback)
# ---------------------------------------------------------------------------

def cmd_play(args: argparse.Namespace) -> None:
    engine = SearchEngine()
    print("=== Deeper-Blue Interactive Mode ===")
    print("Enter a FEN string and the engine will suggest its best move.")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            fen = input("FEN> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if fen.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        if not fen:
            continue

        try:
            board = chess.Board(fen)
        except ValueError:
            print("  [ERROR] Invalid FEN string.\n")
            continue

        print(f"  Board:\n{board}\n")
        move, score = engine.search(board, max_depth=args.depth, time_limit=args.time)

        if move is None:
            print("  No legal moves (game over?)\n")
        else:
            print(f"  Best move: {move.uci()} ({board.san(move)})  score: {score:+d} cp\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sub-command: download-positions
# ---------------------------------------------------------------------------

def cmd_download_positions(args: argparse.Namespace) -> None:
    """Stream Lichess Standard database and extract quiet positions for Texel tuning."""
    from tuning.data_loader import (
        build_url, stream_extract_positions, extract_from_pgn, save_positions,
    )

    output = args.output or "data/positions.json.gz"

    if args.pgn:
        # Local PGN file — no download needed
        if not os.path.isfile(args.pgn):
            print(f"[ERROR] PGN file not found: {args.pgn}")
            sys.exit(1)
        print(f"Extracting from local file: {args.pgn}")
        positions = extract_from_pgn(
            args.pgn,
            max_positions=args.n,
            min_elo=args.min_elo,
        )
    else:
        # Stream from Lichess (stops early — no full file download)
        url = args.url or build_url(args.year, args.month)
        print(f"Lichess Standard DB  {args.year}-{args.month:02d}  (ELO ≥ {args.min_elo})")
        try:
            positions = stream_extract_positions(
                url,
                max_positions=args.n,
                min_elo=args.min_elo,
            )
        except Exception as exc:
            print(f"\n[ERROR] {exc}")
            print("\nAlternatives:")
            print("  1. Try a different month:  --month 6")
            print("  2. Use a local PGN file:   --pgn /path/to/games.pgn")
            sys.exit(1)

    print(f"\nCollected {len(positions):,} positions.")
    save_positions(positions, output)


# ---------------------------------------------------------------------------
# Sub-command: tune
# ---------------------------------------------------------------------------

def cmd_tune(args: argparse.Namespace) -> None:
    """Run Texel tuning on evaluation parameters."""
    from tuning.texel_tuner import tune, save_params, load_params, print_diff

    if not os.path.isfile(args.positions):
        print(f"[ERROR] Positions file not found: {args.positions}")
        print("  Run first:  python main.py download-positions")
        sys.exit(1)

    from tuning.data_loader import load_positions
    print(f"Loading positions from {args.positions}...")
    positions = load_positions(args.positions)
    print(f"  {len(positions):,} positions loaded.\n")

    initial_params = None
    if args.params and os.path.isfile(args.params):
        initial_params = load_params(args.params)
        print(f"Starting from existing params: {args.params}\n")

    n_workers = args.workers or os.cpu_count() or 4

    print("=== Texel Tuning ===")
    best_params = tune(
        positions=positions,
        initial_params=initial_params,
        include_pst=args.pst,
        n_workers=n_workers,
        max_iter=args.iter,
    )

    output = args.output or "data/tuned_params.json"
    save_params(best_params, output)

    print_diff(best_params)
    print(f"\nTo use tuned params, load them in your code:")
    print(f"  from tuning.texel_tuner import load_params")
    print(f"  from engine.evaluation import evaluate_with_params")
    print(f"  params = load_params('{output}')")
    print(f"  score  = evaluate_with_params(board, params)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deeper-blue",
        description="Deeper-Blue: Algorithm-based chess engine vs Deep Blue 1997",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sf_kwargs = dict(default=None, metavar="PATH",
                     help="Path to Stockfish binary (auto-detected if omitted)")

    # --- compare ---
    p_compare = sub.add_parser("compare", help="Compare our engine vs Deep Blue's 1997 moves")
    p_compare.add_argument("--pgn", default="data/pgn", metavar="DIR",
                            help="Directory containing PGN files (default: data/pgn)")
    p_compare.add_argument("--depth", type=int, default=4, metavar="N",
                            help="Search depth for our engine (default: 4)")
    p_compare.add_argument("--time", type=float, default=5.0, metavar="SEC",
                            help="Time limit per move in seconds (default: 5.0)")
    p_compare.add_argument("--verbose", action="store_true",
                            help="Print per-position results")
    p_compare.add_argument("--output", default=None, metavar="FILE",
                            help="Save detailed CSV results to FILE")
    p_compare.add_argument("--charts", default=None, const="", nargs="?", metavar="DIR",
                            help="Generate charts after comparison. Saves to DIR if given, else displays in window.")
    p_compare.add_argument("--stockfish", **sf_kwargs)

    # --- visualize ---
    p_vis = sub.add_parser("visualize", help="Render charts from a saved CSV result file")
    p_vis.add_argument("--csv", required=True, metavar="FILE",
                        help="CSV file produced by 'compare --output'")
    p_vis.add_argument("--charts", default=None, metavar="DIR",
                        help="Save charts to DIR instead of displaying in window")

    # --- analyze ---
    p_analyze = sub.add_parser("analyze", help="Analyze a single FEN position")
    p_analyze.add_argument("--fen", required=True, metavar="FEN",
                            help="FEN string to analyze")
    p_analyze.add_argument("--depth", type=int, default=5, metavar="N",
                            help="Search depth (default: 5)")
    p_analyze.add_argument("--time", type=float, default=10.0, metavar="SEC",
                            help="Time limit in seconds (default: 10.0)")
    p_analyze.add_argument("--stockfish", **sf_kwargs)

    # --- play ---
    p_play = sub.add_parser("play", help="Interactive FEN-input mode (CLI)")
    p_play.add_argument("--depth", type=int, default=4, metavar="N",
                         help="Search depth (default: 4)")
    p_play.add_argument("--time", type=float, default=5.0, metavar="SEC",
                         help="Time limit per move (default: 5.0)")

    # --- play-human ---
    p_human = sub.add_parser("play-human", help="Interactive GUI: play against Deeper-Blue (pygame)")
    p_human.add_argument("--color", default="white", choices=["white", "black"],
                          help="Your piece color (default: white)")
    p_human.add_argument("--depth", type=int, default=4, metavar="N",
                          help="Engine search depth (default: 4)")
    p_human.add_argument("--time", type=float, default=5.0, metavar="SEC",
                          help="Engine time limit per move (default: 5.0)")

    # --- match ---
    p_match = sub.add_parser(
        "match",
        help="Play games against an external UCI engine (Crafty, limited Stockfish, etc.)",
    )
    p_match.add_argument("--opponent", required=True, metavar="PATH",
                          help="Path to opponent UCI engine binary")
    p_match.add_argument("--elo", type=int, default=None, metavar="N",
                          help="Limit Stockfish opponent to this ELO (e.g. 2200 ≈ 1997-era)")
    p_match.add_argument("--games", type=int, default=10, metavar="N",
                          help="Number of games to play (default: 10)")
    p_match.add_argument("--depth", type=int, default=4, metavar="N",
                          help="Deeper-Blue search depth (default: 4)")
    p_match.add_argument("--time", type=float, default=2.0, metavar="SEC",
                          help="Time per move in seconds for both engines (default: 2.0)")
    p_match.add_argument("--output", default=None, metavar="FILE",
                          help="Save game-by-game results to CSV")

    # --- download-positions ---
    p_dl = sub.add_parser(
        "download-positions",
        help="Stream Lichess Standard DB and extract quiet positions for Texel tuning",
    )
    p_dl.add_argument("--year",    type=int, default=2024, metavar="YYYY",
                       help="Year to stream from Lichess (default: 2024)")
    p_dl.add_argument("--month",   type=int, default=1,    metavar="MM",
                       help="Month 1-12 (default: 1)")
    p_dl.add_argument("--n",       type=int, default=200_000, metavar="N",
                       help="Max positions to collect (default: 200000)")
    p_dl.add_argument("--min-elo", type=int, default=2200, metavar="ELO",
                       help="Minimum ELO filter (default: 2200)")
    p_dl.add_argument("--output",  default=None, metavar="FILE",
                       help="Output path (default: data/positions.json.gz)")
    p_dl.add_argument("--pgn",     default=None, metavar="FILE",
                       help="Use a local .pgn / .pgn.gz file instead of downloading")
    p_dl.add_argument("--url",     default=None, metavar="URL",
                       help="Override the Lichess URL (advanced)")

    # --- tune ---
    p_tune = sub.add_parser(
        "tune",
        help="Run Texel tuning to optimize evaluation weights (run on GPU server)",
    )
    p_tune.add_argument("--positions", default="data/positions.json.gz", metavar="FILE",
                         help="Positions file from download-positions (default: data/positions.json.gz)")
    p_tune.add_argument("--params",  default=None, metavar="FILE",
                         help="JSON file with starting EvalParams (default: hand-tuned values)")
    p_tune.add_argument("--output",  default=None, metavar="FILE",
                         help="Where to save tuned params (default: data/tuned_params.json)")
    p_tune.add_argument("--pst",     action="store_true",
                         help="Also tune all 8 PST tables (538 params total, slower)")
    p_tune.add_argument("--iter",    type=int, default=300, metavar="N",
                         help="Max L-BFGS-B iterations (default: 300)")
    p_tune.add_argument("--workers", type=int, default=None, metavar="N",
                         help="CPU workers (default: all available cores)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "compare":             cmd_compare,
        "visualize":           cmd_visualize,
        "analyze":             cmd_analyze,
        "play":                cmd_play,
        "play-human":          cmd_play_human,
        "match":               cmd_match,
        "download-positions":  cmd_download_positions,
        "tune":                cmd_tune,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
