"""
Headless renderer for presentation images.

Renders the *real* Pygame interface (board + evaluation bar + side panel)
off-screen via the SDL "dummy" video driver, plus a couple of matplotlib
charts.  Run from the repo root:

    python image/_generate.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chess
import pygame

from game.chess_gui import (
    ChessGUI, WIN_WIDTH, WIN_HEIGHT, BOARD_SIZE,
)
from engine.minimax import MATE_SCORE
from engine.evaluation import evaluate

OUT = os.path.dirname(os.path.abspath(__file__))


def _new_gui():
    gui = ChessGUI(player_color=chess.WHITE)
    pygame.init()
    gui.screen = pygame.display.set_mode((WIN_WIDTH, WIN_HEIGHT))
    gui._load_fonts()
    gui.overlay = pygame.Surface((BOARD_SIZE, BOARD_SIZE), pygame.SRCALPHA)
    return gui


def _render(gui, *, fen, history, status, eval_score=None,
            last_move=None, game_over=False, filename):
    gui.board = chess.Board(fen)
    gui.move_history = history
    gui.status_msg = status
    gui.game_over = game_over
    gui.engine_thinking = False
    gui.last_move = last_move
    gui.eval_score = evaluate(gui.board) if eval_score is None else eval_score
    gui._draw()
    path = os.path.join(OUT, filename)
    pygame.image.save(gui.screen, path)
    print(f"  saved {filename}  (eval={gui.eval_score:+d}cp)")


def _san_history(moves_san):
    """Replay SAN moves from start, return (fen, history, last_move)."""
    board = chess.Board()
    hist = []
    last = None
    for san in moves_san:
        last = board.push_san(san)
        hist.append(san)
    return board.fen(), hist, last


def render_interface_shots():
    gui = _new_gui()

    # 1) Interface — real middlegame (Najdorf Sicilian opening line)
    fen, hist, last = _san_history(
        ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6",
         "Nc3", "a6", "Be2", "e5", "Nb3", "Be7", "O-O", "O-O"]
    )
    _render(gui, fen=fen, history=hist, last_move=last,
            status="Your move (White)",
            filename="interface_midgame.png")

    # 2) Evaluation bar — White up a queen (decisive). Real evaluate() output.
    _render(gui,
            fen="rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            history=["...", "..."],
            status="White is winning",
            filename="interface_eval_decisive.png")

    # 3) Checkmate — Scholar's mate final position (Black is mated)
    _render(gui,
            fen="r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4",
            history=["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"],
            status="Checkmate — White wins",
            eval_score=MATE_SCORE,
            game_over=True,
            filename="interface_checkmate.png")

    pygame.quit()


def render_winrate_chart():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    versions = ["v1\n(Python d4)", "v2\n(SEE fix)", "v5\n(C engine 8s)"]
    winrate = [22.7, 27.3, 31.8]
    colors = ["#9bb7d4", "#5a8fc7", "#2f6fb3"]

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    bars = ax.bar(versions, winrate, color=colors, width=0.6, edgecolor="white")
    for b, v in zip(bars, winrate):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.6, f"{v:.1f}%",
                ha="center", va="bottom", fontsize=12, fontweight="bold")
    ax.set_ylabel("Win rate vs Deep Blue moves (%)")
    ax.set_title("Deep Blue Move-Comparison: Win Rate by Version\n(22 middlegame positions, Stockfish-judged)")
    ax.set_ylim(0, 40)
    ax.axhline(50, color="grey", ls="--", lw=0.8, alpha=0.0)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = os.path.join(OUT, "winrate_progression.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    print("  saved winrate_progression.png")


def _board_image(gui, fen_before, uci):
    """Render board-only PIL image of the position *after* playing `uci`."""
    from PIL import Image
    b = chess.Board(fen_before)
    mv = chess.Move.from_uci(uci)
    san = b.san(mv)
    b.push(mv)
    gui.board = b
    gui.last_move = mv
    gui.move_history = []
    gui.status_msg = ""
    gui.game_over = False
    gui.eval_score = 0
    gui._draw()
    surf = gui.screen.subsurface(pygame.Rect(0, 0, BOARD_SIZE, BOARD_SIZE)).copy()
    raw = pygame.image.tostring(surf, "RGB")
    return Image.frombytes("RGB", (BOARD_SIZE, BOARD_SIZE), raw), san


def render_deepblue_highlight():
    """Side-by-side: our move vs Deep Blue's actual move (Game 1, move 16)."""
    from PIL import Image, ImageDraw, ImageFont

    fen = "r3r1k1/ppbn1p2/2p2n1p/q2pp1pb/4P3/PP1P2PP/1BPNQPBN/R4RK1 b - - 2 16"
    gui = _new_gui()
    left_img, our_san = _board_image(gui, fen, "h5e2")   # ours, Black +6.9
    right_img, db_san = _board_image(gui, fen, "a5b6")   # Deep Blue, Black -0.4
    pygame.quit()

    def font(sz, bold=False):
        for name in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, sz)
            except Exception:
                continue
        return ImageFont.load_default()

    B = BOARD_SIZE
    margin, head, cap = 24, 70, 70
    W = B * 2 + margin * 3
    H = head + B + cap
    canvas = Image.new("RGB", (W, H), (28, 30, 34))
    d = ImageDraw.Draw(canvas)

    title = "Game 1, move 16  -  Deeper-Blue (Black) vs Deep Blue's actual move"
    d.text((margin, 22), title, fill=(240, 240, 240), font=font(22, True))

    canvas.paste(left_img, (margin, head))
    canvas.paste(right_img, (margin * 2 + B, head))

    cy = head + B + 10
    green, red = (120, 210, 120), (225, 120, 120)
    d.text((margin, cy), f"OURS: {our_san}", fill=green, font=font(22, True))
    d.text((margin, cy + 30), "Stockfish: Black +6.9  (winning)",
           fill=(210, 210, 210), font=font(17))
    d.text((margin * 2 + B, cy), f"DEEP BLUE: {db_san}", fill=red, font=font(22, True))
    d.text((margin * 2 + B, cy + 30), "Stockfish: Black -0.4   ->  delta +7.3, OUR MOVE WINS",
           fill=(210, 210, 210), font=font(17))

    path = os.path.join(OUT, "deepblue_highlight_g1.png")
    canvas.save(path)
    print("  saved deepblue_highlight_g1.png")


def render_elo_progression():
    """Match score% vs ELO-limited Stockfish across versions v3/v4/v5."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    groups = ["vs ELO 1500", "vs ELO 2000"]
    x = np.arange(2)
    w = 0.26
    v3 = [40.0, 5.0]      # 10 games each
    v4 = [85.0, 42.5]     # 20 games each (reliable baseline)
    v5_1500 = 85.7        # 7 clean games
    v5_2000_partial = 70.0  # 5 clean games (3W/1D/1L), sleep-interrupted

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.bar(x - w, v3, w, label="v3 (C engine)", color="#cc5555")
    ax.bar(x, v4, w, label="v4 (qsearch fix, 20G)", color="#5a8fc7")
    ax.bar(x[0] + w, v5_1500, w, label="v5 (+watchdog)", color="#2f6fb3")
    ax.bar(x[1] + w, v5_2000_partial, w, color="#2f6fb3",
           hatch="//", alpha=0.5, edgecolor="white")

    for xi, val in zip(x - w, v3):
        ax.text(xi, val + 1.5, f"{val:.0f}%", ha="center", fontsize=9)
    for xi, val in zip(x, v4):
        ax.text(xi, val + 1.5, f"{val:.1f}%", ha="center", fontsize=9)
    ax.text(x[0] + w, v5_1500 + 1.5, f"{v5_1500:.1f}%", ha="center", fontsize=9)
    ax.text(x[1] + w, v5_2000_partial + 1.5, "partial\n(n=5)",
            ha="center", fontsize=8, color="#444")

    ax.set_xticks(x)
    ax.set_xticklabels(groups)
    ax.set_ylabel("Score %  (win=1, draw=0.5)")
    ax.set_ylim(0, 100)
    ax.axhline(50, color="grey", ls="--", lw=0.8, alpha=0.5)
    ax.set_title("Match Score vs ELO-limited Stockfish\n"
                 "v3 -> v4: a single qsearch bugfix; v5 2000 partial (host sleep)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "elo_progression.png"), dpi=140)
    plt.close(fig)
    print("  saved elo_progression.png")


if __name__ == "__main__":
    print("Rendering interface screenshots...")
    render_interface_shots()
    print("Rendering Deep Blue highlight...")
    render_deepblue_highlight()
    print("Rendering charts...")
    render_winrate_chart()
    render_elo_progression()
    print("Done.")
