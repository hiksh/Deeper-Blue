"""
chess_gui.py

Pygame-based interactive chess GUI for playing against the Deeper-Blue engine.

Layout
------
  ┌─────────────────────────────────┬────────────────┐
  │                                 │  INFO PANEL    │
  │         CHESS BOARD             │  - Status      │
  │          (560×560)              │  - Move history│
  │                                 │  - Controls    │
  └─────────────────────────────────┴────────────────┘

Controls
--------
  - Left-click piece  : select (shows legal moves in green)
  - Left-click target : move
  - R key             : restart game
  - Q / Esc           : quit
  - F key             : flip board
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import chess
import pygame
import pygame.freetype

from engine.minimax import SearchEngine

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
SQUARE_SIZE   = 70
BOARD_SIZE    = SQUARE_SIZE * 8        # 560
PANEL_WIDTH   = 280
WIN_WIDTH     = BOARD_SIZE + PANEL_WIDTH
WIN_HEIGHT    = BOARD_SIZE
FPS           = 60

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
C_LIGHT       = (240, 217, 181)   # light square
C_DARK        = (181, 136,  99)   # dark square
C_SELECTED    = ( 20, 200,  20, 160)  # selected piece (with alpha)
C_LEGAL       = ( 50, 200,  50, 120)  # legal move dot
C_LAST_MOVE   = (205, 210,  60, 140)  # last move highlight
C_CHECK       = (220,  50,  50, 160)  # king in check
C_PANEL_BG    = ( 30,  30,  30)
C_PANEL_LINE  = ( 60,  60,  60)
C_TEXT        = (230, 230, 230)
C_TEXT_DIM    = (140, 140, 140)
C_ACCENT      = ( 52, 152, 219)   # blue accent
C_WIN_TEXT    = (255, 215,   0)   # gold

# ---------------------------------------------------------------------------
# Unicode chess pieces
# ---------------------------------------------------------------------------
PIECE_UNICODE = {
    (chess.KING,   chess.WHITE): "♔",
    (chess.QUEEN,  chess.WHITE): "♕",
    (chess.ROOK,   chess.WHITE): "♖",
    (chess.BISHOP, chess.WHITE): "♗",
    (chess.KNIGHT, chess.WHITE): "♘",
    (chess.PAWN,   chess.WHITE): "♙",
    (chess.KING,   chess.BLACK): "♚",
    (chess.QUEEN,  chess.BLACK): "♛",
    (chess.ROOK,   chess.BLACK): "♜",
    (chess.BISHOP, chess.BLACK): "♝",
    (chess.KNIGHT, chess.BLACK): "♞",
    (chess.PAWN,   chess.BLACK): "♟",
}

ENGINE_DEPTH   = 4
ENGINE_TIME    = 5.0


class ChessGUI:
    """
    Full pygame chess GUI.

    Parameters
    ----------
    player_color : chess.WHITE or chess.BLACK (which side the human plays)
    engine_depth : search depth for Deeper-Blue
    engine_time  : time limit per move (seconds)
    """

    def __init__(
        self,
        player_color: chess.Color = chess.WHITE,
        engine_depth: int = ENGINE_DEPTH,
        engine_time:  float = ENGINE_TIME,
    ) -> None:
        self.player_color  = player_color
        self.engine_depth  = engine_depth
        self.engine_time   = engine_time

        self.board         = chess.Board()
        self.engine        = SearchEngine()
        self.flipped       = (player_color == chess.BLACK)

        self.selected_sq: Optional[int] = None
        self.legal_targets: set[int]    = set()
        self.last_move: Optional[chess.Move] = None

        self.engine_thinking = False
        self.engine_move_result: Optional[chess.Move] = None

        self.move_history: list[str] = []   # SAN strings
        self.history_scroll = 0             # scroll offset (lines)
        self.status_msg = ""
        self.game_over = False

        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Deeper-Blue Chess")
        self.screen = pygame.display.set_mode((WIN_WIDTH, WIN_HEIGHT))
        self.clock  = pygame.time.Clock()

        # Load fonts (freetype for unicode piece support)
        self._load_fonts()

        # Overlay surface for transparent highlights
        self.overlay = pygame.Surface((BOARD_SIZE, BOARD_SIZE), pygame.SRCALPHA)

        self._update_status()

        # If engine plays first (human is Black), start engine thread
        if self.board.turn != self.player_color and not self.game_over:
            self._start_engine_thread()

        running = True
        while running:
            self.clock.tick(FPS)

            # Collect engine result safely
            self._collect_engine_result()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_q, pygame.K_ESCAPE):
                        running = False
                    elif event.key == pygame.K_r:
                        self._restart()
                    elif event.key == pygame.K_f:
                        self.flipped = not self.flipped
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_click(event.pos)

            self._draw()
            pygame.display.flip()

        pygame.quit()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        self.screen.fill(C_PANEL_BG)
        self._draw_board()
        self._draw_highlights()
        self._draw_pieces()
        self._draw_coords()
        self._draw_panel()

    def _draw_board(self) -> None:
        for rank in range(8):
            for file in range(8):
                sq    = self._visual_to_sq(file, rank)
                color = C_LIGHT if (file + rank) % 2 == 0 else C_DARK
                rect  = pygame.Rect(file * SQUARE_SIZE, rank * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
                pygame.draw.rect(self.screen, color, rect)

    def _draw_highlights(self) -> None:
        self.overlay.fill((0, 0, 0, 0))

        # Last move
        if self.last_move:
            for sq in (self.last_move.from_square, self.last_move.to_square):
                f, r = self._sq_to_visual(sq)
                rect = pygame.Rect(f * SQUARE_SIZE, r * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
                pygame.draw.rect(self.overlay, C_LAST_MOVE, rect)

        # King in check
        if self.board.is_check():
            king_sq = self.board.king(self.board.turn)
            if king_sq is not None:
                f, r = self._sq_to_visual(king_sq)
                rect = pygame.Rect(f * SQUARE_SIZE, r * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
                pygame.draw.rect(self.overlay, C_CHECK, rect)

        # Selected square
        if self.selected_sq is not None:
            f, r = self._sq_to_visual(self.selected_sq)
            rect = pygame.Rect(f * SQUARE_SIZE, r * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
            pygame.draw.rect(self.overlay, C_SELECTED, rect)

        # Legal move dots
        for sq in self.legal_targets:
            f, r = self._sq_to_visual(sq)
            cx = f * SQUARE_SIZE + SQUARE_SIZE // 2
            cy = r * SQUARE_SIZE + SQUARE_SIZE // 2
            if self.board.piece_at(sq):
                # Capture: ring
                pygame.draw.circle(self.overlay, C_LEGAL, (cx, cy), SQUARE_SIZE // 2 - 4, 5)
            else:
                # Quiet: dot
                pygame.draw.circle(self.overlay, C_LEGAL, (cx, cy), SQUARE_SIZE // 6)

        self.screen.blit(self.overlay, (0, 0))

    def _draw_pieces(self) -> None:
        for sq in chess.SQUARES:
            piece = self.board.piece_at(sq)
            if piece is None:
                continue
            symbol = PIECE_UNICODE[(piece.piece_type, piece.color)]
            f, r   = self._sq_to_visual(sq)
            cx = f * SQUARE_SIZE + SQUARE_SIZE // 2
            cy = r * SQUARE_SIZE + SQUARE_SIZE // 2

            # Shadow
            shadow_surf, shadow_rect = self.piece_font.render(symbol, (30, 30, 30))
            shadow_rect.center = (cx + 2, cy + 2)
            self.screen.blit(shadow_surf, shadow_rect)

            # Piece
            color = (255, 255, 255) if piece.color == chess.WHITE else (20, 20, 20)
            piece_surf, piece_rect = self.piece_font.render(symbol, color)
            piece_rect.center = (cx, cy)
            self.screen.blit(piece_surf, piece_rect)

    def _draw_coords(self) -> None:
        for i in range(8):
            # Rank numbers (left edge)
            rank_idx = 7 - i if not self.flipped else i
            rank_char = str(rank_idx + 1)
            surf, rect = self.coord_font.render(rank_char, C_TEXT_DIM)
            self.screen.blit(surf, (3, i * SQUARE_SIZE + 3))

            # File letters (bottom edge)
            file_idx = i if not self.flipped else 7 - i
            file_char = chr(ord('a') + file_idx)
            surf, rect = self.coord_font.render(file_char, C_TEXT_DIM)
            self.screen.blit(surf, (i * SQUARE_SIZE + SQUARE_SIZE - 12, BOARD_SIZE - 16))

    def _draw_panel(self) -> None:
        px = BOARD_SIZE
        panel_rect = pygame.Rect(px, 0, PANEL_WIDTH, WIN_HEIGHT)
        pygame.draw.rect(self.screen, C_PANEL_BG, panel_rect)
        pygame.draw.line(self.screen, C_PANEL_LINE, (px, 0), (px, WIN_HEIGHT), 2)

        y = 14
        # Title
        self._panel_text("DEEPER-BLUE", px + 10, y, self.title_font, C_ACCENT)
        y += 30
        pygame.draw.line(self.screen, C_PANEL_LINE, (px + 8, y), (px + PANEL_WIDTH - 8, y))
        y += 12

        # Player sides
        human_side  = "White" if self.player_color == chess.WHITE else "Black"
        engine_side = "Black" if self.player_color == chess.WHITE else "White"
        self._panel_text(f"You:    {human_side}", px + 10, y, self.info_font, C_TEXT)
        y += 22
        self._panel_text(f"Engine: {engine_side}", px + 10, y, self.info_font, C_TEXT)
        y += 30

        pygame.draw.line(self.screen, C_PANEL_LINE, (px + 8, y), (px + PANEL_WIDTH - 8, y))
        y += 12

        # Status
        status_color = C_WIN_TEXT if self.game_over else C_ACCENT if self.engine_thinking else C_TEXT
        self._panel_text(self.status_msg, px + 10, y, self.info_font, status_color)
        y += 30

        pygame.draw.line(self.screen, C_PANEL_LINE, (px + 8, y), (px + PANEL_WIDTH - 8, y))
        y += 12

        # Move history header
        self._panel_text("Move History", px + 10, y, self.info_font, C_TEXT_DIM)
        y += 22

        # Move history list
        history_area_height = WIN_HEIGHT - y - 60
        lines_visible = history_area_height // 18
        pairs = []
        for i in range(0, len(self.move_history), 2):
            num = i // 2 + 1
            w = self.move_history[i]
            b = self.move_history[i + 1] if i + 1 < len(self.move_history) else "..."
            pairs.append(f"{num:>3}. {w:<8} {b}")

        start = max(0, len(pairs) - lines_visible)
        for pair in pairs[start:]:
            self._panel_text(pair, px + 10, y, self.mono_font, C_TEXT)
            y += 18

        # Controls hint at bottom
        hint_y = WIN_HEIGHT - 48
        pygame.draw.line(self.screen, C_PANEL_LINE, (px + 8, hint_y - 6), (px + PANEL_WIDTH - 8, hint_y - 6))
        self._panel_text("[R] New game   [F] Flip   [Q] Quit", px + 10, hint_y, self.hint_font, C_TEXT_DIM)
        y2 = hint_y + 18
        depth_str = f"Depth: {self.engine_depth}   Time: {self.engine_time:.0f}s"
        self._panel_text(depth_str, px + 10, y2, self.hint_font, C_TEXT_DIM)

    def _panel_text(self, text: str, x: int, y: int, font, color) -> None:
        try:
            surf, rect = font.render(text, color)
            self.screen.blit(surf, (x, y))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _handle_click(self, pos: tuple[int, int]) -> None:
        x, y = pos
        if x >= BOARD_SIZE:
            return  # clicked panel
        if self.engine_thinking or self.game_over:
            return
        if self.board.turn != self.player_color:
            return

        file_v = x // SQUARE_SIZE
        rank_v = y // SQUARE_SIZE
        sq = self._visual_to_sq(file_v, rank_v)

        if self.selected_sq is None:
            # Select a piece
            piece = self.board.piece_at(sq)
            if piece and piece.color == self.player_color:
                self.selected_sq = sq
                self.legal_targets = {
                    m.to_square for m in self.board.legal_moves
                    if m.from_square == sq
                }
        else:
            if sq in self.legal_targets:
                # Attempt the move
                move = self._build_move(self.selected_sq, sq)
                if move:
                    self._apply_move(move)
                    self.selected_sq = None
                    self.legal_targets = set()
                    # Start engine if game not over
                    if not self.game_over:
                        self._start_engine_thread()
            elif sq == self.selected_sq:
                # Deselect
                self.selected_sq = None
                self.legal_targets = set()
            else:
                # Select different piece
                piece = self.board.piece_at(sq)
                if piece and piece.color == self.player_color:
                    self.selected_sq = sq
                    self.legal_targets = {
                        m.to_square for m in self.board.legal_moves
                        if m.from_square == sq
                    }
                else:
                    self.selected_sq = None
                    self.legal_targets = set()

    def _build_move(self, from_sq: int, to_sq: int) -> Optional[chess.Move]:
        """Build a move, handling pawn promotion (auto-queen)."""
        piece = self.board.piece_at(from_sq)
        promotion = None
        if piece and piece.piece_type == chess.PAWN:
            to_rank = chess.square_rank(to_sq)
            if (piece.color == chess.WHITE and to_rank == 7) or \
               (piece.color == chess.BLACK and to_rank == 0):
                promotion = chess.QUEEN  # auto-promote to queen
        move = chess.Move(from_sq, to_sq, promotion=promotion)
        if move in self.board.legal_moves:
            return move
        return None

    # ------------------------------------------------------------------
    # Move application
    # ------------------------------------------------------------------

    def _apply_move(self, move: chess.Move) -> None:
        san = self.board.san(move)
        self.board.push(move)
        self.last_move = move
        self.move_history.append(san)
        self._check_game_over()
        self._update_status()

    def _check_game_over(self) -> None:
        if self.board.is_game_over():
            self.game_over = True

    def _update_status(self) -> None:
        if self.board.is_checkmate():
            winner = "Black" if self.board.turn == chess.WHITE else "White"
            self.status_msg = f"Checkmate! {winner} wins"
        elif self.board.is_stalemate():
            self.status_msg = "Stalemate — Draw"
        elif self.board.is_insufficient_material():
            self.status_msg = "Insufficient material — Draw"
        elif self.board.is_fifty_moves():
            self.status_msg = "50-move rule — Draw"
        elif self.board.is_repetition(3):
            self.status_msg = "Threefold repetition — Draw"
        elif self.engine_thinking:
            self.status_msg = "Engine thinking..."
        elif self.board.turn == self.player_color:
            check = " (Check!)" if self.board.is_check() else ""
            self.status_msg = f"Your turn{check}"
        else:
            self.status_msg = "Engine's turn"

    # ------------------------------------------------------------------
    # Engine thread
    # ------------------------------------------------------------------

    def _start_engine_thread(self) -> None:
        self.engine_thinking = True
        self.engine_move_result = None
        self._update_status()
        t = threading.Thread(target=self._engine_worker, daemon=True)
        t.start()

    def _engine_worker(self) -> None:
        board_copy = self.board.copy()
        self.engine.tt.clear()
        move, score = self.engine.search(
            board_copy,
            max_depth=self.engine_depth,
            time_limit=self.engine_time,
        )
        with self._lock:
            self.engine_move_result = move

    def _collect_engine_result(self) -> None:
        if not self.engine_thinking:
            return
        with self._lock:
            move = self.engine_move_result
        if move is None:
            return
        # Engine finished
        self.engine_thinking = False
        if not self.game_over:
            if move in self.board.legal_moves:
                self._apply_move(move)
            else:
                self.status_msg = "Engine error — no legal move"
        with self._lock:
            self.engine_move_result = None

    # ------------------------------------------------------------------
    # Restart
    # ------------------------------------------------------------------

    def _restart(self) -> None:
        self.board         = chess.Board()
        self.engine        = SearchEngine()
        self.selected_sq   = None
        self.legal_targets = set()
        self.last_move     = None
        self.engine_thinking = False
        self.engine_move_result = None
        self.move_history  = []
        self.game_over     = False
        self._update_status()

        if self.board.turn != self.player_color and not self.game_over:
            self._start_engine_thread()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _sq_to_visual(self, sq: int) -> tuple[int, int]:
        """Square index → (file_visual, rank_visual) for drawing."""
        file = chess.square_file(sq)
        rank = chess.square_rank(sq)
        if not self.flipped:
            return file, 7 - rank
        else:
            return 7 - file, rank

    def _visual_to_sq(self, file_v: int, rank_v: int) -> int:
        """(file_visual, rank_visual) → square index."""
        if not self.flipped:
            return chess.square(file_v, 7 - rank_v)
        else:
            return chess.square(7 - file_v, rank_v)

    # ------------------------------------------------------------------
    # Font loading
    # ------------------------------------------------------------------

    def _load_fonts(self) -> None:
        pygame.freetype.init()

        # Piece font — try fonts with good unicode chess symbol support
        piece_size = int(SQUARE_SIZE * 0.72)
        piece_font_loaded = False
        for font_name in ["Segoe UI Symbol", "Arial Unicode MS", "DejaVu Sans", "FreeSerif"]:
            try:
                self.piece_font = pygame.freetype.SysFont(font_name, piece_size)
                # Test render
                self.piece_font.render("♔", (255, 255, 255))
                piece_font_loaded = True
                break
            except Exception:
                continue
        if not piece_font_loaded:
            self.piece_font = pygame.freetype.SysFont(None, piece_size)

        self.title_font = pygame.freetype.SysFont("Segoe UI", 20, bold=True)
        self.info_font  = pygame.freetype.SysFont("Segoe UI", 14)
        self.mono_font  = pygame.freetype.SysFont("Consolas", 13)
        self.coord_font = pygame.freetype.SysFont("Segoe UI", 11)
        self.hint_font  = pygame.freetype.SysFont("Segoe UI", 11)


# ---------------------------------------------------------------------------
# Entry point helper
# ---------------------------------------------------------------------------

def launch(
    player_color: chess.Color = chess.WHITE,
    engine_depth: int = ENGINE_DEPTH,
    engine_time:  float = ENGINE_TIME,
) -> None:
    gui = ChessGUI(
        player_color=player_color,
        engine_depth=engine_depth,
        engine_time=engine_time,
    )
    gui.run()
