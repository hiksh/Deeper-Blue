"""
web/app.py

Flask backend for the Deeper-Blue web chess interface.

API Endpoints
-------------
GET  /                  Serve the chess UI
POST /api/new_game      Start a new game  { "player_color": "white"|"black" }
POST /api/move          Human makes a move { "move": "e2e4" (UCI) }
GET  /api/state         Get current board state

Deploy
------
Local:  python web/app.py
Render: set start command to  gunicorn web.app:app
"""

import math
import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template, request, session
import chess

from engine.minimax import SearchEngine
from engine.evaluation import evaluate as _evaluate

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "deeper-blue-secret-2024")

# ---------------------------------------------------------------------------
# In-memory game store (session-keyed)
# For production multi-user deploy, replace with Redis or DB.
# ---------------------------------------------------------------------------
_games: dict[str, dict] = {}

ENGINE_DEPTH = int(os.environ.get("ENGINE_DEPTH", "4"))
ENGINE_TIME  = float(os.environ.get("ENGINE_TIME",  "5.0"))


def _get_game(session_id: str) -> dict | None:
    return _games.get(session_id)


def _new_game(session_id: str, player_color: str = "white") -> dict:
    game = {
        "board":        chess.Board(),
        "engine":       SearchEngine(),
        "player_color": chess.WHITE if player_color == "white" else chess.BLACK,
        "move_history": [],   # list of SAN strings
        "status":       "playing",
    }
    _games[session_id] = game
    return game


def _board_state(game: dict) -> dict:
    board: chess.Board = game["board"]
    eval_cp, eval_str = _compute_eval(board)
    return {
        "fen":          board.fen(),
        "turn":         "white" if board.turn == chess.WHITE else "black",
        "player_color": "white" if game["player_color"] == chess.WHITE else "black",
        "move_history": game["move_history"],
        "status":       game["status"],
        "in_check":     board.is_check(),
        "legal_moves":  [m.uci() for m in board.legal_moves],
        "last_move":    game["move_history"][-1] if game["move_history"] else None,
        "eval_cp":      eval_cp,
        "eval_str":     eval_str,
    }


def _compute_eval(board: chess.Board) -> tuple[int, str]:
    """Return (centipawns_white_perspective, display_string)."""
    if board.is_game_over():
        return 0, "0.00"
    cp = _evaluate(board)
    if abs(cp) >= 29_000:
        ply_to_mate = 30_000 - abs(cp)
        moves_to_mate = math.ceil(ply_to_mate / 2)
        sign = "+" if cp > 0 else "-"
        return cp, f"{sign}M{moves_to_mate}"
    return cp, f"{cp / 100:+.2f}"


def _apply_move(game: dict, move: chess.Move) -> None:
    board: chess.Board = game["board"]
    san = board.san(move)
    board.push(move)
    game["move_history"].append(san)
    _update_status(game)


def _update_status(game: dict) -> None:
    board: chess.Board = game["board"]
    if board.is_checkmate():
        winner = "Black" if board.turn == chess.WHITE else "White"
        game["status"] = f"checkmate:{winner.lower()}"
    elif board.is_stalemate():
        game["status"] = "draw:stalemate"
    elif board.is_insufficient_material():
        game["status"] = "draw:insufficient"
    elif board.is_fifty_moves():
        game["status"] = "draw:fifty_moves"
    elif board.is_repetition(3):
        game["status"] = "draw:repetition"
    else:
        game["status"] = "playing"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/new_game", methods=["POST"])
def new_game():
    data         = request.get_json(silent=True) or {}
    player_color = data.get("player_color", "white")
    session_id   = _ensure_session()

    game = _new_game(session_id, player_color)
    state = _board_state(game)

    # If engine plays first (player is Black), make engine move immediately
    if game["player_color"] == chess.BLACK:
        engine_result = _engine_move(game)
        state = _board_state(game)
        state["engine_move"] = engine_result

    return jsonify({"ok": True, "state": state})


@app.route("/api/move", methods=["POST"])
def make_move():
    session_id = _ensure_session()
    game = _get_game(session_id)
    if not game:
        return jsonify({"ok": False, "error": "No active game. Call /api/new_game first."}), 400

    board: chess.Board = game["board"]

    if game["status"] != "playing":
        return jsonify({"ok": False, "error": "Game is over."}), 400

    if board.turn != game["player_color"]:
        return jsonify({"ok": False, "error": "Not your turn."}), 400

    data = request.get_json(silent=True) or {}
    uci  = data.get("move", "")

    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return jsonify({"ok": False, "error": f"Invalid UCI: {uci}"}), 400

    if move not in board.legal_moves:
        return jsonify({"ok": False, "error": "Illegal move."}), 400

    _apply_move(game, move)

    engine_result = None
    if game["status"] == "playing":
        engine_result = _engine_move(game)

    state = _board_state(game)
    state["engine_move"] = engine_result
    return jsonify({"ok": True, "state": state})


@app.route("/api/state", methods=["GET"])
def get_state():
    session_id = _ensure_session()
    game = _get_game(session_id)
    if not game:
        return jsonify({"ok": False, "error": "No active game."}), 404
    return jsonify({"ok": True, "state": _board_state(game)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_session() -> str:
    if "id" not in session:
        import uuid
        session["id"] = str(uuid.uuid4())
    return session["id"]


def _engine_move(game: dict) -> str | None:
    """Run the engine and apply its move. Returns UCI string of the move."""
    board: chess.Board = game["board"]
    engine: SearchEngine = game["engine"]
    engine.tt.clear()
    move, _ = engine.search(board, max_depth=ENGINE_DEPTH, time_limit=ENGINE_TIME)
    if move and move in board.legal_moves:
        _apply_move(game, move)
        return move.uci()
    return None


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
