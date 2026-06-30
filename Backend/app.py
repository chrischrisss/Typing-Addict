import os
import random
import warnings
from datetime import UTC, datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    decode_token,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    unset_jwt_cookies,
)
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import check_password_hash, generate_password_hash

from games import calc_score, calc_wpm, check_progress, pick_prompt, score_clicking, score_spacebar
from models import GameControl, GameResult, GameSession, Lobby, Player, User, UserProfile, Viewer, db


CODE_CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GAME_ORDER = ("typing", "clicking", "spacebar")
ROUND_DURATION = 30
START_COUNTDOWN_DURATION = 3


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


def is_render():
    return os.environ.get("RENDER") == "true"


def resolve_database_url():
    database_url = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
    if not database_url.startswith("sqlite:"):
        return database_url

    if database_url.startswith("sqlite:////"):
        db_path = "/" + database_url.removeprefix("sqlite:////")
    elif database_url.startswith("sqlite:///"):
        db_path = database_url.removeprefix("sqlite:///")
    else:
        return database_url

    db_path = os.path.abspath(db_path)
    db_dir = os.path.dirname(db_path)
    if not db_dir:
        return database_url

    try:
        os.makedirs(db_dir, exist_ok=True)
    except OSError:
        if is_render():
            fallback = "sqlite:///db.sqlite3"
            warnings.warn(
                f"Could not create database directory {db_dir}; falling back to {fallback}. "
                "Attach a Render persistent disk mounted at /data to keep SQLite data across deploys.",
                stacklevel=2,
            )
            return fallback
        raise

    if not os.access(db_dir, os.W_OK):
        if is_render():
            fallback = "sqlite:///db.sqlite3"
            warnings.warn(
                f"Database directory {db_dir} is not writable; falling back to {fallback}.",
                stacklevel=2,
            )
            return fallback
        raise PermissionError(f"Database directory is not writable: {db_dir}")

    return database_url


def socket_cors_origins():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        return [render_url.rstrip("/")]

    configured = os.environ.get("SOCKET_CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]

    return ["http://127.0.0.1:5173", "http://localhost:5173"]


app = Flask(__name__)

if is_render():
    CORS(app, supports_credentials=True, origins=socket_cors_origins())
else:
    CORS(app, supports_credentials=True)

app.config["SQLALCHEMY_DATABASE_URI"] = resolve_database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.environ.get(
    "JWT_SECRET_KEY",
    "development-only-secret-change-before-production",
)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", app.config["JWT_SECRET_KEY"])
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = is_render()
app.config["JWT_COOKIE_SAMESITE"] = "Lax"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

db.init_app(app)
JWTManager(app)

socketio = SocketIO(
    app,
    cors_allowed_origins=socket_cors_origins(),
    manage_session=False,
)


with app.app_context():
    db.create_all()

    if not User.query.first():
        user = User(
            username="admin",
            password_hash=generate_password_hash("password"),
        )
        db.session.add(user)
        db.session.commit()


@app.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if len(username) < 3 or len(username) > 30:
        return jsonify({"message": "Username must be 3 to 30 characters."}), 400

    if len(password) < 8:
        return jsonify({"message": "Password must be at least 8 characters."}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"message": "That username is already taken."}), 409

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    response = jsonify({"message": "Account created."})
    set_access_cookies(response, token)
    return response, 201


@app.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"message": "Username and password are required."}), 400

    user = User.query.filter_by(username=username).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"message": "Invalid username or password."}), 401

    token = create_access_token(identity=str(user.id))
    response = jsonify({"message": "Login successful."})
    set_access_cookies(response, token)
    return response


@app.get("/me")
@jwt_required()
def me():
    user = db.session.get(User, int(get_jwt_identity()))

    if not user:
        return jsonify({"message": "User not found."}), 404

    return jsonify({
        "user_id": user.id,
        "username": user.username,
        "display_name": user.profile.display_name if user.profile else None,
    })


@app.put("/me/profile")
@jwt_required()
def update_profile():
    data = request.get_json(silent=True) or {}
    display_name = " ".join(str(data.get("display_name", "")).strip().split())

    if len(display_name) < 3 or len(display_name) > 18:
        return jsonify({"message": "Display name must be 3 to 18 characters."}), 400

    if not all(character.isalnum() or character in " _-" for character in display_name):
        return jsonify({"message": "Display name contains unsupported characters."}), 400

    user_id = int(get_jwt_identity())
    profile = UserProfile.query.filter_by(user_id=user_id).first()

    if profile:
        profile.display_name = display_name
    else:
        db.session.add(UserProfile(user_id=user_id, display_name=display_name))

    db.session.commit()
    return jsonify({"display_name": display_name})


@app.post("/logout")
def logout():
    response = jsonify({"message": "Logged out."})
    unset_jwt_cookies(response)
    return response


def generate_lobby_code():
    while True:
        code = "".join(random.choice(CODE_CHARACTERS) for _ in range(6))
        if any(character.isalpha() for character in code) and any(
            character.isdigit() for character in code
        ):
            return code


def generate_unique_lobby_code():
    while True:
        code = generate_lobby_code()
        if not Lobby.query.filter_by(code=code).first():
            return code


def find_lobby(code):
    clean_code = str(code).strip().upper()

    if len(clean_code) != 6:
        return None

    return Lobby.query.filter_by(code=clean_code).first()


def lobby_membership(lobby_id, user_id):
    if Player.query.filter_by(lobby_id=lobby_id, user_id=user_id).first():
        return "player"

    if Viewer.query.filter_by(lobby_id=lobby_id, user_id=user_id).first():
        return "viewer"

    return None


def display_name_for(user):
    return user.profile.display_name if user.profile else user.username


def lobby_members(lobby):
    players = Player.query.filter_by(lobby_id=lobby.id).all()
    viewers = Viewer.query.filter_by(lobby_id=lobby.id).all()

    return {
        "players": [
            {
                "user_id": player.user_id,
                "name": display_name_for(player.user),
                "role": "host" if player.user_id == lobby.host_user_id else "player",
                "score": player.score,
            }
            for player in players
        ],
        "viewers": [
            {
                "user_id": viewer.user_id,
                "name": display_name_for(viewer.user),
                "role": "viewer",
            }
            for viewer in viewers
        ],
    }


def game_control(session):
    control = GameControl.query.filter_by(game_session_id=session.id).first()
    if control:
        return control

    control = GameControl(
        game_session_id=session.id,
        round_index=0,
        phase="countdown",
        round_started_at=utc_now() + timedelta(seconds=START_COUNTDOWN_DURATION),
    )
    db.session.add(control)
    db.session.commit()
    return control


def sync_game_control(lobby, session, control):
    now = utc_now()
    changed = False

    if control.phase == "countdown" and now >= control.round_started_at:
        control.phase = "running"
        changed = True

    if control.phase == "running":
        elapsed = max(0, (now - control.round_started_at).total_seconds())
        player_count = Player.query.filter_by(lobby_id=lobby.id).count()
        result_count = GameResult.query.filter_by(
            game_session_id=session.id,
            round_index=control.round_index,
        ).count()
        if elapsed >= ROUND_DURATION or (player_count > 0 and result_count >= player_count):
            control.phase = "leaderboard"
            changed = True

    if changed:
        db.session.commit()


def round_state(lobby, session, control):
    sync_game_control(lobby, session, control)
    game_type = GAME_ORDER[control.round_index]
    elapsed = max(0, (utc_now() - control.round_started_at).total_seconds())

    if control.phase == "countdown":
        seconds = max(1, round((control.round_started_at - utc_now()).total_seconds()))
    elif control.phase == "running":
        seconds = max(0, round(ROUND_DURATION - elapsed))
    else:
        seconds = 0

    return {
        "phase": control.phase,
        "round_index": control.round_index,
        "game_type": game_type,
        "next_game_type": (
            GAME_ORDER[control.round_index + 1]
            if control.round_index < len(GAME_ORDER) - 1
            else None
        ),
        "seconds_remaining": seconds,
        "elapsed_seconds": min(ROUND_DURATION, max(0.01, elapsed)),
    }


def game_payload(lobby, session=None):
    session = session or GameSession.query.filter_by(lobby_id=lobby.id).first()
    if not session:
        return None

    control = game_control(session)
    state = round_state(lobby, session, control)
    results = GameResult.query.filter_by(game_session_id=session.id).all()
    names = {member["user_id"]: member["name"] for member in lobby_members(lobby)["players"]}
    totals = {user_id: 0 for user_id in names}
    previous_totals = {user_id: 0 for user_id in names}
    round_scores = {user_id: 0 for user_id in names}

    for result in results:
        totals[result.user_id] = totals.get(result.user_id, 0) + result.score
        if result.round_index < state["round_index"]:
            previous_totals[result.user_id] = previous_totals.get(result.user_id, 0) + result.score
        elif result.round_index == state["round_index"]:
            round_scores[result.user_id] = result.score

    previous_order = [
        user_id
        for user_id, _ in sorted(previous_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    sorted_totals = sorted(totals.items(), key=lambda item: item[1], reverse=True)

    state.update({
        "session_id": session.id,
        "game_order": list(GAME_ORDER),
        "round_duration": ROUND_DURATION,
        "host_user_id": lobby.host_user_id,
        "prompt": session.typing_prompt if state["round_index"] == 0 else None,
        "results": [
            {
                "user_id": result.user_id,
                "name": names.get(result.user_id, "Former player"),
                "round_index": result.round_index,
                "score": result.score,
                "metric": result.metric,
                "accuracy": result.accuracy,
            }
            for result in results
        ],
        "standings": [
            {
                "user_id": user_id,
                "name": names.get(user_id, "Former player"),
                "score": score,
                "round_score": round_scores.get(user_id, 0),
                "previous_rank": previous_order.index(user_id) if user_id in previous_order else None,
            }
            for user_id, score in sorted_totals
        ],
    })
    return state


def lobby_payload(lobby, role=None, include_members=False):
    player_count = Player.query.filter_by(lobby_id=lobby.id).count()
    viewer_count = Viewer.query.filter_by(lobby_id=lobby.id).count()

    payload = {
        "code": lobby.code,
        "name": lobby.name,
        "host_user_id": lobby.host_user_id,
        "player_limit": lobby.player_limit,
        "viewer_limit": lobby.viewer_limit,
        "player_count": player_count,
        "viewer_count": viewer_count,
    }

    if role:
        payload["role"] = role

    if include_members:
        payload.update(lobby_members(lobby))
        payload["game"] = game_payload(lobby)

    return payload


def lobby_room(code):
    return f"lobby:{code}"


def broadcast_lobby(lobby):
    socketio.emit(
        "lobby:updated",
        lobby_payload(lobby, include_members=True),
        room=lobby_room(lobby.code),
    )


def broadcast_game(lobby, session=None):
    payload = game_payload(lobby, session)
    if payload:
        socketio.emit("game:state", payload, room=lobby_room(lobby.code))


def broadcast_lobby_closed(code, message="Lobby closed."):
    socketio.emit(
        "lobby:closed",
        {"code": code, "message": message},
        room=lobby_room(code),
    )


def membership_role(lobby, user_id):
    role = lobby_membership(lobby.id, user_id)
    if role == "player" and lobby.host_user_id == user_id:
        return "host"
    return role


@socketio.on("connect")
def handle_connect():
    token = request.cookies.get("access_token_cookie")
    if not token:
        return False

    try:
        user_id = int(decode_token(token)["sub"])
    except Exception:
        return False

    code = str(request.args.get("lobby", "")).strip().upper()
    lobby = find_lobby(code)
    if not lobby or not membership_role(lobby, user_id):
        return False

    join_room(lobby_room(lobby.code))
    emit("lobby:updated", lobby_payload(lobby, include_members=True))
    game = game_payload(lobby)
    if game:
        emit("game:state", game)
    return True


def tick_active_games():
    controls = GameControl.query.filter(
        GameControl.phase.in_(["countdown", "running"])
    ).all()
    for control in controls:
        session = db.session.get(GameSession, control.game_session_id)
        if not session:
            continue
        lobby = db.session.get(Lobby, session.lobby_id)
        if not lobby:
            continue
        sync_game_control(lobby, session, control)
        broadcast_game(lobby, session)


def game_tick_loop():
    while True:
        socketio.sleep(0.5)
        with app.app_context():
            if app.config.get("TESTING"):
                continue
            try:
                tick_active_games()
            except Exception:
                db.session.rollback()
            finally:
                db.session.remove()


_tick_loop_started = False


def start_game_tick_loop():
    global _tick_loop_started
    if _tick_loop_started or app.config.get("TESTING"):
        return
    _tick_loop_started = True
    socketio.start_background_task(game_tick_loop)


@app.post("/lobbies")
@jwt_required()
def create_lobby():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    player_limit = data.get("player_limit")
    viewer_limit = data.get("viewer_limit")

    if len(name) < 3 or len(name) > 32:
        return jsonify({"message": "Lobby name must be 3 to 32 characters."}), 400

    try:
        player_limit = int(player_limit)
        viewer_limit = int(viewer_limit)
    except (TypeError, ValueError):
        return jsonify({"message": "Player and viewer limits must be numbers."}), 400

    if player_limit < 2 or player_limit > 12:
        return jsonify({"message": "Player size must be between 2 and 12."}), 400

    if viewer_limit < 0 or viewer_limit > 100:
        return jsonify({"message": "Viewer size must be between 0 and 100."}), 400

    user_id = int(get_jwt_identity())
    code = generate_unique_lobby_code()

    lobby = Lobby(
        code=code,
        name=name,
        host_user_id=user_id,
        player_limit=player_limit,
        viewer_limit=viewer_limit,
    )
    db.session.add(lobby)
    db.session.flush()

    db.session.add(
        Player(
            user_id=user_id,
            lobby_id=lobby.id,
            score=0,
        )
    )
    db.session.commit()

    return jsonify(lobby_payload(lobby, "host", include_members=True)), 201


@app.get("/lobbies/<code>")
@jwt_required()
def get_lobby(code):
    lobby = find_lobby(code)

    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    role = lobby_membership(lobby.id, user_id)
    if role == "player" and lobby.host_user_id == user_id:
        role = "host"

    return jsonify(lobby_payload(lobby, role, include_members=bool(role)))


@app.post("/lobbies/<code>/join")
@jwt_required()
def join_lobby(code):
    data = request.get_json(silent=True) or {}
    role = str(data.get("role", "player")).strip().lower()

    if role not in ("player", "viewer"):
        return jsonify({"message": "Join as a player or a viewer."}), 400

    lobby = find_lobby(code)

    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    existing_role = lobby_membership(lobby.id, user_id)

    if existing_role:
        if lobby.host_user_id == user_id and existing_role == "player":
            response_role = "host"
        else:
            response_role = existing_role

        return jsonify(lobby_payload(lobby, response_role, include_members=True))

    if role == "player":
        if GameSession.query.filter_by(lobby_id=lobby.id).first():
            return jsonify({"message": "This game has already started."}), 409

        player_count = Player.query.filter_by(lobby_id=lobby.id).count()

        if player_count >= lobby.player_limit:
            return jsonify({"message": "That lobby is full."}), 409

        db.session.add(
            Player(
                user_id=user_id,
                lobby_id=lobby.id,
                score=0,
            )
        )
        response_role = "host" if lobby.host_user_id == user_id else "player"
    else:
        if lobby.viewer_limit <= 0:
            return jsonify({"message": "This lobby has no viewer slots."}), 409

        viewer_count = Viewer.query.filter_by(lobby_id=lobby.id).count()

        if viewer_count >= lobby.viewer_limit:
            return jsonify({"message": "Viewer slots are full."}), 409

        db.session.add(
            Viewer(
                user_id=user_id,
                lobby_id=lobby.id,
            )
        )
        response_role = "viewer"

    db.session.commit()
    broadcast_lobby(lobby)

    return jsonify(lobby_payload(lobby, response_role, include_members=True))


def delete_lobby_data(lobby):
    session = GameSession.query.filter_by(lobby_id=lobby.id).first()
    if session:
        GameControl.query.filter_by(game_session_id=session.id).delete()
        GameResult.query.filter_by(game_session_id=session.id).delete()
        db.session.delete(session)

    Player.query.filter_by(lobby_id=lobby.id).delete()
    Viewer.query.filter_by(lobby_id=lobby.id).delete()
    db.session.delete(lobby)


@app.delete("/lobbies/<code>/leave")
@jwt_required()
def leave_lobby(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    player = Player.query.filter_by(lobby_id=lobby.id, user_id=user_id).first()
    viewer = Viewer.query.filter_by(lobby_id=lobby.id, user_id=user_id).first()
    if not player and not viewer:
        return jsonify({"message": "You are not in this lobby."}), 404

    was_host = lobby.host_user_id == user_id
    if player:
        db.session.delete(player)
    if viewer:
        db.session.delete(viewer)
    db.session.flush()

    next_host = None
    if was_host:
        remaining_players = Player.query.filter_by(lobby_id=lobby.id).all()
        if remaining_players:
            next_host = random.choice(remaining_players)
            lobby.host_user_id = next_host.user_id
        else:
            remaining_viewers = Viewer.query.filter_by(lobby_id=lobby.id).all()
            if remaining_viewers:
                promoted = random.choice(remaining_viewers)
                next_host = Player(user_id=promoted.user_id, lobby_id=lobby.id, score=0)
                db.session.delete(promoted)
                db.session.add(next_host)
                lobby.host_user_id = next_host.user_id

    has_players = Player.query.filter_by(lobby_id=lobby.id).count() > 0
    has_viewers = Viewer.query.filter_by(lobby_id=lobby.id).count() > 0
    if not has_players and not has_viewers:
        lobby_code = lobby.code
        delete_lobby_data(lobby)
        db.session.commit()
        broadcast_lobby_closed(lobby_code)
        return jsonify({"message": "Left lobby.", "lobby_closed": True})

    db.session.commit()
    broadcast_lobby(lobby)
    return jsonify({
        "message": "Left lobby.",
        "lobby_closed": False,
        "host_user_id": lobby.host_user_id,
    })


@app.delete("/lobbies/<code>/players/<int:target_user_id>")
@jwt_required()
def kick_player(code, target_user_id):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    if lobby.host_user_id != user_id:
        return jsonify({"message": "Only the host can kick players."}), 403
    if target_user_id == user_id:
        return jsonify({"message": "Use Leave lobby to leave."}), 400

    player = Player.query.filter_by(lobby_id=lobby.id, user_id=target_user_id).first()
    if not player:
        return jsonify({"message": "Player not found."}), 404

    db.session.delete(player)
    db.session.commit()
    broadcast_lobby(lobby)
    return jsonify({"message": "Player kicked."})


@app.post("/lobbies/<code>/start")
@jwt_required()
def start_lobby_game(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    if lobby.host_user_id != user_id:
        return jsonify({"message": "Only the host can start the game."}), 403

    existing = GameSession.query.filter_by(lobby_id=lobby.id).first()
    if existing:
        return jsonify(game_payload(lobby, existing))

    session = GameSession(
        lobby_id=lobby.id,
        started_at=utc_now() + timedelta(seconds=START_COUNTDOWN_DURATION),
        typing_prompt=pick_prompt(),
    )
    db.session.add(session)
    db.session.flush()
    db.session.add(GameControl(
        game_session_id=session.id,
        round_index=0,
        phase="countdown",
        round_started_at=session.started_at,
    ))
    db.session.commit()
    broadcast_lobby(lobby)
    broadcast_game(lobby, session)
    return jsonify(game_payload(lobby, session)), 201


@app.post("/lobbies/<code>/next")
@jwt_required()
def start_next_round(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    if lobby.host_user_id != user_id:
        return jsonify({"message": "Only the host can start the next round."}), 403

    session = GameSession.query.filter_by(lobby_id=lobby.id).first()
    if not session:
        return jsonify({"message": "The game has not started."}), 409

    control = game_control(session)
    sync_game_control(lobby, session, control)
    if control.phase != "leaderboard":
        return jsonify({"message": "Finish the current round first."}), 409

    if control.round_index >= len(GAME_ORDER) - 1:
        control.phase = "finished"
    else:
        control.round_index += 1
        control.phase = "countdown"
        control.round_started_at = utc_now() + timedelta(seconds=START_COUNTDOWN_DURATION)

    db.session.commit()
    broadcast_game(lobby, session)
    return jsonify(game_payload(lobby, session))


@app.get("/lobbies/<code>/game")
@jwt_required()
def get_lobby_game(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    if not lobby_membership(lobby.id, user_id):
        return jsonify({"message": "You are no longer in this lobby."}), 403

    game = game_payload(lobby)
    if not game:
        return jsonify({"message": "The game has not started."}), 404
    return jsonify(game)


@app.post("/lobbies/<code>/game/submit")
@jwt_required()
def submit_game_result(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    player = Player.query.filter_by(lobby_id=lobby.id, user_id=user_id).first()
    if not player:
        return jsonify({"message": "Only players can submit results."}), 403

    session = GameSession.query.filter_by(lobby_id=lobby.id).first()
    if not session:
        return jsonify({"message": "The game has not started."}), 409

    data = request.get_json(silent=True) or {}
    try:
        submitted_round = int(data.get("round_index"))
    except (TypeError, ValueError):
        return jsonify({"message": "Round index is required."}), 400

    control = game_control(session)
    state = round_state(lobby, session, control)
    if (
        submitted_round < 0
        or submitted_round >= len(GAME_ORDER)
        or submitted_round > state["round_index"]
        or (
            submitted_round == state["round_index"]
            and state["phase"] not in ("running", "leaderboard")
        )
    ):
        return jsonify({"message": "That round is not accepting results."}), 409

    existing = GameResult.query.filter_by(
        game_session_id=session.id,
        user_id=user_id,
        round_index=submitted_round,
    ).first()
    if existing:
        return jsonify({"score": existing.score, "message": "Result already submitted."})

    elapsed = (
        state.get("elapsed_seconds", ROUND_DURATION)
        if submitted_round == state["round_index"]
        else ROUND_DURATION
    )
    elapsed = min(ROUND_DURATION, max(0.01, elapsed))
    game_type = GAME_ORDER[submitted_round]
    accuracy = None

    if game_type == "typing":
        typed = str(data.get("typed", ""))[:500]
        progress = check_progress(session.typing_prompt, typed)
        metric = calc_wpm(progress["correct"], elapsed)
        accuracy = progress["accuracy"]
        score = calc_score(metric, accuracy)
    else:
        try:
            count = max(0, min(10000, int(data.get("count", 0))))
        except (TypeError, ValueError):
            return jsonify({"message": "A valid action count is required."}), 400

        scored = score_clicking(count, elapsed) if game_type == "clicking" else score_spacebar(count, elapsed)
        metric = scored["cps"]
        score = scored["score"]

    result = GameResult(
        game_session_id=session.id,
        user_id=user_id,
        round_index=submitted_round,
        score=score,
        metric=metric,
        accuracy=accuracy,
    )
    db.session.add(result)
    db.session.flush()
    player.score = sum(
        row.score
        for row in GameResult.query.filter_by(game_session_id=session.id, user_id=user_id).all()
    )
    player_count = Player.query.filter_by(lobby_id=lobby.id).count()
    submitted_count = GameResult.query.filter_by(
        game_session_id=session.id,
        round_index=submitted_round,
    ).count()
    if (
        submitted_round == control.round_index
        and player_count > 0
        and submitted_count >= player_count
    ):
        control.phase = "leaderboard"
    db.session.commit()
    broadcast_game(lobby, session)
    return jsonify({"score": score, "metric": metric, "accuracy": accuracy}), 201


STATIC_DIR = os.path.join(app.root_path, "static")


def register_frontend_routes():
    if not os.path.isdir(STATIC_DIR):
        return

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        if path:
            asset_path = os.path.join(STATIC_DIR, path)
            if os.path.isfile(asset_path):
                return send_from_directory(STATIC_DIR, path)
        return send_from_directory(STATIC_DIR, "index.html")


register_frontend_routes()

if is_render():
    start_game_tick_loop()


if __name__ == "__main__":
    start_game_tick_loop()
    socketio.run(app, debug=True, port=5000, use_reloader=False)