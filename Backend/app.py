import os
import random
import warnings
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

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
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from games import calc_score, calc_wpm, check_progress, pick_prompt, score_clicking, score_spacebar
from models import Bet, Bidder, GameControl, GameResult, GameSession, Lobby, Player, User, UserProfile, db


CODE_CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GAME_TYPES = ("typing", "clicking", "spacebar")
DEFAULT_ROUND_DURATION = 30
START_COUNTDOWN_DURATION = 3
INSTRUCTION_DURATION = 30
BETTING_DURATION = 20
RESULT_GRACE_DURATION = 2
STARTING_BALANCE_CENTS = 100000
REBUY_CENTS = 5000
LIVE_PROGRESS = {}
ACTION_PROGRESS_TARGETS = {
    "clicking": 100,
    "spacebar": 100,
}


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


def migrate_legacy_role_schema():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    if "lobby" in tables:
        columns = {column["name"] for column in inspector.get_columns("lobby")}
        if "bidder_limit" not in columns and "gambler_limit" in columns:
            db.session.execute(text(
                "ALTER TABLE lobby RENAME COLUMN gambler_limit TO bidder_limit"
            ))
        elif "bidder_limit" not in columns and "viewer_limit" in columns:
            db.session.execute(text(
                "ALTER TABLE lobby RENAME COLUMN viewer_limit TO bidder_limit"
            ))

    if "bidder" not in tables and "gambler" in tables:
        db.session.execute(text("ALTER TABLE gambler RENAME TO bidder"))
    elif "bidder" not in tables and "viewer" in tables:
        db.session.execute(text("ALTER TABLE viewer RENAME TO bidder"))

    if "bet" in tables:
        columns = {column["name"] for column in inspector.get_columns("bet")}
        if "bidder_user_id" not in columns and "gambler_user_id" in columns:
            db.session.execute(text(
                "ALTER TABLE bet RENAME COLUMN gambler_user_id TO bidder_user_id"
            ))

    db.session.commit()


def ensure_lobby_settings_columns():
    existing = {column["name"] for column in inspect(db.engine).get_columns("lobby")}
    added_lobby_limit = "lobby_limit" not in existing
    settings = {
        "lobby_limit": 100,
        "bidder_limit": 0,
        "typing_rounds": 1,
        "clicking_rounds": 1,
        "spacebar_rounds": 1,
        "round_duration": DEFAULT_ROUND_DURATION,
    }
    for column, default in settings.items():
        if column not in existing:
            db.session.execute(text(
                f"ALTER TABLE lobby ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}"
            ))
    if added_lobby_limit:
        db.session.execute(text(
            "UPDATE lobby SET lobby_limit = CASE "
            "WHEN player_limit + bidder_limit > 100 THEN 100 "
            "ELSE player_limit + bidder_limit END"
        ))
    db.session.execute(text(
        "UPDATE lobby SET bidder_limit = 50 WHERE bidder_limit > 50"
    ))
    db.session.commit()


def ensure_betting_columns():
    bidder_columns = {column["name"] for column in inspect(db.engine).get_columns("bidder")}
    if "balance_cents" not in bidder_columns:
        db.session.execute(text(
            f"ALTER TABLE bidder ADD COLUMN balance_cents INTEGER NOT NULL "
            f"DEFAULT {STARTING_BALANCE_CENTS}"
        ))

    control_columns = {
        column["name"] for column in inspect(db.engine).get_columns("game_control")
    }
    if "betting_settled" not in control_columns:
        db.session.execute(text(
            "ALTER TABLE game_control ADD COLUMN betting_settled BOOLEAN NOT NULL DEFAULT FALSE"
        ))
    db.session.commit()


with app.app_context():
    migrate_legacy_role_schema()
    db.create_all()
    ensure_lobby_settings_columns()
    ensure_betting_columns()

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

    if Bidder.query.filter_by(lobby_id=lobby_id, user_id=user_id).first():
        return "bidder"

    return None


def display_name_for(user):
    return user.profile.display_name if user.profile else user.username


def is_admin_user(user_id):
    user = db.session.get(User, user_id)
    return bool(user and user.username.lower() == "admin")


def lobby_members(lobby):
    players = Player.query.filter_by(lobby_id=lobby.id).all()
    bidders = Bidder.query.filter_by(lobby_id=lobby.id).all()

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
        "bidders": [
            {
                "user_id": bidder.user_id,
                "name": display_name_for(bidder.user),
                "role": "bidder",
                "balance": bidder.balance_cents / 100,
            }
            for bidder in bidders
        ],
    }


def game_order_for(lobby):
    return (
        ["typing"] * lobby.typing_rounds
        + ["clicking"] * lobby.clicking_rounds
        + ["spacebar"] * lobby.spacebar_rounds
    )


def start_betting_phase(lobby, control, round_index):
    if round_index > 0:
        for bidder in Bidder.query.filter_by(lobby_id=lobby.id).all():
            if bidder.balance_cents <= 0:
                bidder.balance_cents = REBUY_CENTS

    control.round_index = round_index
    control.phase = "betting"
    control.round_started_at = utc_now() + timedelta(seconds=BETTING_DURATION)
    control.betting_settled = False


def round_winning_player_ids(lobby, session, round_index):
    player_ids = {
        player.user_id for player in Player.query.filter_by(lobby_id=lobby.id).all()
    }
    results = GameResult.query.filter_by(
        game_session_id=session.id,
        round_index=round_index,
    ).all()
    scores = {user_id: 0 for user_id in player_ids}
    for result in results:
        scores[result.user_id] = result.score
    if not scores:
        return set()
    top_score = max(scores.values())
    return {user_id for user_id, score in scores.items() if score == top_score}


def settle_round_bets(lobby, session, control):
    if control.betting_settled:
        return

    bets = Bet.query.filter_by(
        game_session_id=session.id,
        round_index=control.round_index,
    ).all()
    winning_player_ids = round_winning_player_ids(lobby, session, control.round_index)
    winning_bets = [bet for bet in bets if bet.player_user_id in winning_player_ids]

    for bet in bets:
        bet.won = bet in winning_bets
        # The stake was removed when the bid was placed. A correct bid gets the
        # stake back plus an equal profit; every other finishing position loses.
        bet.payout_cents = bet.amount_cents * 2 if bet.won else 0
        if bet.won:
            bidder = Bidder.query.filter_by(
                lobby_id=lobby.id,
                user_id=bet.bidder_user_id,
            ).first()
            if bidder:
                bidder.balance_cents += bet.payout_cents

    control.betting_settled = True


def betting_payload(lobby, session, control):
    bets = Bet.query.filter_by(
        game_session_id=session.id,
        round_index=control.round_index,
    ).all()
    members = lobby_members(lobby)
    player_names = {player["user_id"]: player["name"] for player in members["players"]}
    bidder_names = {bidder["user_id"]: bidder["name"] for bidder in members["bidders"]}
    winning_player_ids = (
        round_winning_player_ids(lobby, session, control.round_index)
        if control.betting_settled
        else set()
    )
    placed_bets = [
        {
            "bidder_user_id": bet.bidder_user_id,
            "player_user_id": bet.player_user_id,
            "player_name": player_names.get(bet.player_user_id, "Former player (left)"),
            "amount": bet.amount_cents / 100,
        }
        for bet in bets
    ]

    return {
        "duration": BETTING_DURATION,
        "pot": sum(bet.amount_cents for bet in bets) / 100,
        "bettor_ids": [bet.bidder_user_id for bet in bets],
        "bets": placed_bets,
        "bidders": members["bidders"],
        "winning_players": [
            {
                "user_id": user_id,
                "name": player_names.get(user_id, "Former player (left)"),
            }
            for user_id in winning_player_ids
        ],
        "winners": [
            {
                "user_id": bet.bidder_user_id,
                "name": bidder_names.get(
                    bet.bidder_user_id,
                    display_name_for(db.session.get(User, bet.bidder_user_id)),
                ),
                "player_user_id": bet.player_user_id,
                "player_name": player_names.get(bet.player_user_id, "Former player (left)"),
                "wager": bet.amount_cents / 100,
                "payout": (bet.payout_cents or 0) / 100,
            }
            for bet in bets
            if bet.won
        ],
        "settled": control.betting_settled,
    }


def game_control(session):
    control = GameControl.query.filter_by(game_session_id=session.id).first()
    if control:
        return control

    control = GameControl(
        game_session_id=session.id,
        round_index=0,
        phase="instructions",
        round_started_at=utc_now() + timedelta(seconds=INSTRUCTION_DURATION),
        betting_settled=False,
    )
    db.session.add(control)
    db.session.commit()
    return control


def sync_game_control(lobby, session, control):
    now = utc_now()
    changed = False

    if control.phase == "instructions" and now >= control.round_started_at:
        control.phase = "betting"
        control.round_started_at += timedelta(seconds=BETTING_DURATION)
        changed = True

    if control.phase == "betting" and now >= control.round_started_at:
        control.phase = "countdown"
        control.round_started_at += timedelta(seconds=START_COUNTDOWN_DURATION)
        changed = True

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
        if elapsed >= lobby.round_duration or (player_count > 0 and result_count >= player_count):
            if player_count > 0 and result_count >= player_count:
                control.phase = "leaderboard"
                settle_round_bets(lobby, session, control)
            else:
                control.phase = "settling"
                control.round_started_at = now + timedelta(seconds=RESULT_GRACE_DURATION)
            changed = True

    if control.phase == "settling" and now >= control.round_started_at:
        control.phase = "leaderboard"
        settle_round_bets(lobby, session, control)
        changed = True

    if changed:
        db.session.commit()


def round_state(lobby, session, control):
    sync_game_control(lobby, session, control)
    game_order = game_order_for(lobby)
    game_type = game_order[control.round_index]
    elapsed = max(0, (utc_now() - control.round_started_at).total_seconds())

    if control.phase in ("instructions", "betting", "countdown"):
        seconds = max(1, round((control.round_started_at - utc_now()).total_seconds()))
    elif control.phase == "running":
        seconds = max(0, round(lobby.round_duration - elapsed))
    else:
        seconds = 0

    return {
        "phase": control.phase,
        "round_index": control.round_index,
        "game_type": game_type,
        "next_game_type": (
            game_order[control.round_index + 1]
            if control.round_index < len(game_order) - 1
            else None
        ),
        "seconds_remaining": seconds,
        "elapsed_seconds": (
            lobby.round_duration
            if control.phase in ("settling", "leaderboard", "finished")
            else min(lobby.round_duration, max(0.01, elapsed))
        ),
    }


def game_payload(lobby, session=None):
    session = session or GameSession.query.filter_by(lobby_id=lobby.id).first()
    if not session:
        return None

    control = game_control(session)
    state = round_state(lobby, session, control)
    results = GameResult.query.filter_by(game_session_id=session.id).all()
    names = {member["user_id"]: member["name"] for member in lobby_members(lobby)["players"]}
    result_user_ids = {result.user_id for result in results}
    departed_names = {
        user.id: f"{display_name_for(user)} (left)"
        for user in User.query.filter(User.id.in_(result_user_ids - names.keys())).all()
    }

    def leaderboard_name(user_id):
        return names.get(user_id) or departed_names.get(user_id, "Former player (left)")

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
    current_bidders = lobby_members(lobby)["bidders"]
    bidder_standing_rows = {
        bidder["user_id"]: {
            "user_id": bidder["user_id"],
            "name": bidder["name"],
            "balance": bidder["balance"],
        }
        for bidder in current_bidders
    }
    session_bets = Bet.query.filter_by(game_session_id=session.id).all()
    historical_bidder_ids = {bet.bidder_user_id for bet in session_bets}
    for bidder_user_id in historical_bidder_ids - bidder_standing_rows.keys():
        user = db.session.get(User, bidder_user_id)
        user_bets = [bet for bet in session_bets if bet.bidder_user_id == bidder_user_id]
        balance_cents = STARTING_BALANCE_CENTS + sum(
            (bet.payout_cents or 0) - bet.amount_cents for bet in user_bets
        )
        bidder_standing_rows[bidder_user_id] = {
            "user_id": bidder_user_id,
            "name": f"{display_name_for(user)} (left)" if user else "Former bidder (left)",
            "balance": max(0, balance_cents) / 100,
        }
    bidder_standings = sorted(
        bidder_standing_rows.values(),
        key=lambda bidder: (-bidder["balance"], bidder["name"].lower()),
    )

    state.update({
        "session_id": session.id,
        "game_order": game_order_for(lobby),
        "round_duration": lobby.round_duration,
        "host_user_id": lobby.host_user_id,
        "players": lobby_members(lobby)["players"],
        "betting": betting_payload(lobby, session, control),
        "prompt": session.typing_prompt if state["game_type"] == "typing" else None,
        "live_progress": live_progress_payload(lobby, session, control),
        "results": [
            {
                "user_id": result.user_id,
                "name": leaderboard_name(result.user_id),
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
                "name": leaderboard_name(user_id),
                "score": score,
                "round_score": round_scores.get(user_id, 0),
                "previous_rank": previous_order.index(user_id) if user_id in previous_order else None,
            }
            for user_id, score in sorted_totals
        ],
        "bidder_standings": [
            {
                "user_id": bidder["user_id"],
                "name": bidder["name"],
                "balance": bidder["balance"],
            }
            for bidder in bidder_standings
        ],
    })
    return state


def lobby_payload(lobby, role=None, include_members=False):
    player_count = Player.query.filter_by(lobby_id=lobby.id).count()
    bidder_count = Bidder.query.filter_by(lobby_id=lobby.id).count()

    payload = {
        "code": lobby.code,
        "name": lobby.name,
        "host_user_id": lobby.host_user_id,
        "lobby_limit": lobby.lobby_limit,
        "player_limit": lobby.player_limit,
        "bidder_limit": lobby.bidder_limit,
        "typing_rounds": lobby.typing_rounds,
        "clicking_rounds": lobby.clicking_rounds,
        "spacebar_rounds": lobby.spacebar_rounds,
        "round_duration": lobby.round_duration,
        "player_count": player_count,
        "bidder_count": bidder_count,
    }

    if role:
        payload["role"] = role

    if include_members:
        payload.update(lobby_members(lobby))
        payload["game"] = game_payload(lobby)

    return payload


def lobby_room(code):
    return f"lobby:{code}"


def bidder_room(code):
    return f"lobby:{code}:bidders"


def live_progress_payload(lobby, session, control):
    members = lobby_members(lobby)["players"]
    progress = LIVE_PROGRESS.get((session.id, control.round_index), {})
    game_type = game_order_for(lobby)[control.round_index]

    players = []
    for member in members:
        value = progress.get(member["user_id"], 0)
        if game_type == "typing":
            percent = round((value / max(1, len(session.typing_prompt))) * 100)
        else:
            percent = round((value / ACTION_PROGRESS_TARGETS[game_type]) * 100)
        players.append({
            "user_id": member["user_id"],
            "name": member["name"],
            "progress": min(100, max(0, percent)),
            "value": value,
        })

    players.sort(key=lambda player: (-player["value"], player["name"].lower()))
    return {
        "round_index": control.round_index,
        "game_type": game_type,
        "players": players[:10],
    }


def broadcast_live_progress(lobby, session, control):
    socketio.emit(
        "game:progress",
        live_progress_payload(lobby, session, control),
        room=bidder_room(lobby.code),
    )


def record_live_progress(lobby, user_id, data):
    if lobby_membership(lobby.id, user_id) != "player":
        return None

    session = GameSession.query.filter_by(lobby_id=lobby.id).first()
    if not session:
        return None

    control = game_control(session)
    state = round_state(lobby, session, control)
    data = data if isinstance(data, dict) else {}
    if (
        state["phase"] != "running"
        or data.get("round_index") != control.round_index
        or data.get("game_type") != state["game_type"]
    ):
        return None

    if state["game_type"] == "typing":
        typed = str(data.get("typed", ""))[:len(session.typing_prompt)]
        value = check_progress(session.typing_prompt, typed)["correct"]
    else:
        try:
            value = max(0, min(10000, int(data.get("count", 0))))
        except (TypeError, ValueError):
            return None

    LIVE_PROGRESS.setdefault((session.id, control.round_index), {})[user_id] = value
    return session, control


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
    role = membership_role(lobby, user_id) if lobby else None
    if not lobby or not role:
        return False

    join_room(lobby_room(lobby.code))
    if role == "bidder":
        join_room(bidder_room(lobby.code))
    emit("lobby:updated", lobby_payload(lobby, include_members=True))
    game = game_payload(lobby)
    if game:
        emit("game:state", game)
        if role == "bidder":
            session = GameSession.query.filter_by(lobby_id=lobby.id).first()
            control = game_control(session)
            emit("game:progress", live_progress_payload(lobby, session, control))
    return True


@socketio.on("game:progress:update")
def handle_game_progress(data):
    token = request.cookies.get("access_token_cookie")
    try:
        user_id = int(decode_token(token)["sub"])
    except Exception:
        return

    code = str(request.args.get("lobby", "")).strip().upper()
    lobby = find_lobby(code)
    if not lobby:
        return

    recorded = record_live_progress(lobby, user_id, data)
    if not recorded:
        return
    session, control = recorded
    broadcast_live_progress(lobby, session, control)


def tick_active_games():
    controls = GameControl.query.filter(
        GameControl.phase.in_(["instructions", "betting", "countdown", "running", "settling"])
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
        broadcast_live_progress(lobby, session, control)


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
    lobby_limit = data.get("lobby_limit")
    player_limit = data.get("player_limit")
    bidder_limit = data.get(
        "bidder_limit",
        data.get("gambler_limit", data.get("viewer_limit")),
    )
    typing_rounds = data.get("typing_rounds", 1)
    clicking_rounds = data.get("clicking_rounds", 1)
    spacebar_rounds = data.get("spacebar_rounds", 1)
    round_duration = data.get("round_duration", DEFAULT_ROUND_DURATION)

    if len(name) < 3 or len(name) > 32:
        return jsonify({"message": "Lobby name must be 3 to 32 characters."}), 400

    try:
        player_limit = int(player_limit)
        bidder_limit = int(bidder_limit)
        lobby_limit = (
            min(100, player_limit + bidder_limit)
            if lobby_limit is None
            else int(lobby_limit)
        )
        typing_rounds = int(typing_rounds)
        clicking_rounds = int(clicking_rounds)
        spacebar_rounds = int(spacebar_rounds)
        round_duration = int(round_duration)
    except (TypeError, ValueError):
        return jsonify({"message": "Lobby settings must be whole numbers."}), 400

    if lobby_limit < 1 or lobby_limit > 100:
        return jsonify({"message": "Lobby size must be between 1 and 100."}), 400

    if player_limit < 1 or player_limit > 100:
        return jsonify({"message": "Player size must be between 1 and 100."}), 400

    if bidder_limit < 0 or bidder_limit > 50:
        return jsonify({"message": "Bidder size must be between 0 and 50."}), 400

    round_counts = (typing_rounds, clicking_rounds, spacebar_rounds)
    if any(count < 1 or count > 10 for count in round_counts):
        return jsonify({"message": "Each game mode must have 1 to 10 rounds."}), 400

    if round_duration < 5 or round_duration > 300:
        return jsonify({"message": "Round time must be between 5 and 300 seconds."}), 400

    user_id = int(get_jwt_identity())
    if is_admin_user(user_id):
        return jsonify({"message": "Admin accounts cannot create lobbies."}), 403
    code = generate_unique_lobby_code()

    lobby = Lobby(
        code=code,
        name=name,
        host_user_id=user_id,
        lobby_limit=lobby_limit,
        player_limit=player_limit,
        bidder_limit=bidder_limit,
        typing_rounds=typing_rounds,
        clicking_rounds=clicking_rounds,
        spacebar_rounds=spacebar_rounds,
        round_duration=round_duration,
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
    lobby = find_lobby(code)

    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    if is_admin_user(user_id):
        return jsonify({"message": "Admin accounts cannot join lobbies."}), 403

    existing_role = lobby_membership(lobby.id, user_id)

    if existing_role:
        if lobby.host_user_id == user_id and existing_role == "player":
            response_role = "host"
        else:
            response_role = existing_role

        return jsonify(lobby_payload(lobby, response_role, include_members=True))

    player_count = Player.query.filter_by(lobby_id=lobby.id).count()
    bidder_count = Bidder.query.filter_by(lobby_id=lobby.id).count()
    member_count = player_count + bidder_count
    game_started = GameSession.query.filter_by(lobby_id=lobby.id).first() is not None
    if member_count >= lobby.lobby_limit:
        return jsonify({"message": "This lobby has no open spots."}), 409
    if not game_started and player_count < lobby.player_limit:
        response_role = "player"
    elif lobby.bidder_limit > 0 and bidder_count < lobby.bidder_limit:
        response_role = "bidder"
    else:
        return jsonify({"message": "This lobby has no open spots."}), 409

    if response_role == "player":

        db.session.add(
            Player(
                user_id=user_id,
                lobby_id=lobby.id,
                score=0,
            )
        )
    else:
        db.session.add(
            Bidder(
                user_id=user_id,
                lobby_id=lobby.id,
            )
        )
    db.session.commit()
    broadcast_lobby(lobby)

    return jsonify(lobby_payload(lobby, response_role, include_members=True))


def delete_lobby_data(lobby):
    session = GameSession.query.filter_by(lobby_id=lobby.id).first()
    if session:
        for key in [key for key in LIVE_PROGRESS if key[0] == session.id]:
            LIVE_PROGRESS.pop(key, None)
        Bet.query.filter_by(game_session_id=session.id).delete()
        GameControl.query.filter_by(game_session_id=session.id).delete()
        GameResult.query.filter_by(game_session_id=session.id).delete()
        db.session.delete(session)

    Player.query.filter_by(lobby_id=lobby.id).delete()
    Bidder.query.filter_by(lobby_id=lobby.id).delete()
    db.session.delete(lobby)


def admin_user_rows(admin_id):
    return [
        {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.profile.display_name if user.profile else "",
            "is_admin": user.id == admin_id,
        }
        for user in User.query.order_by(User.username.asc()).all()
    ]


def admin_lobby_rows():
    return [
        {
            "code": lobby.code,
            "name": lobby.name,
            "host_user_id": lobby.host_user_id,
            "host_username": lobby.host.username,
            "host_name": display_name_for(lobby.host),
            "player_count": Player.query.filter_by(lobby_id=lobby.id).count(),
            "lobby_limit": lobby.lobby_limit,
            "player_limit": lobby.player_limit,
            "bidder_count": Bidder.query.filter_by(lobby_id=lobby.id).count(),
            "bidder_limit": lobby.bidder_limit,
        }
        for lobby in Lobby.query.order_by(Lobby.created_at.desc()).all()
    ]


@app.get("/admin/dashboard")
@jwt_required()
def admin_dashboard():
    admin_id = int(get_jwt_identity())
    if not is_admin_user(admin_id):
        return jsonify({"message": "Admin access required."}), 403
    return jsonify({
        "users": admin_user_rows(admin_id),
        "lobbies": admin_lobby_rows(),
    })


@app.get("/admin/users")
@jwt_required()
def admin_users():
    admin_id = int(get_jwt_identity())
    if not is_admin_user(admin_id):
        return jsonify({"message": "Admin access required."}), 403

    return jsonify({"users": admin_user_rows(admin_id)})


@app.put("/admin/users/<int:target_user_id>/profile")
@jwt_required()
def admin_update_user_profile(target_user_id):
    if not is_admin_user(int(get_jwt_identity())):
        return jsonify({"message": "Admin access required."}), 403

    user = db.session.get(User, target_user_id)
    if not user:
        return jsonify({"message": "User not found."}), 404

    data = request.get_json(silent=True) or {}
    display_name = " ".join(str(data.get("display_name", "")).strip().split())
    if len(display_name) < 3 or len(display_name) > 18:
        return jsonify({"message": "Display name must be 3 to 18 characters."}), 400
    if not all(character.isalnum() or character in " _-" for character in display_name):
        return jsonify({"message": "Display name contains unsupported characters."}), 400

    if user.profile:
        user.profile.display_name = display_name
    else:
        db.session.add(UserProfile(user_id=user.id, display_name=display_name))
    db.session.commit()

    lobby_ids = {
        membership.lobby_id
        for membership in [
            *Player.query.filter_by(user_id=user.id).all(),
            *Bidder.query.filter_by(user_id=user.id).all(),
        ]
    }
    for lobby_id in lobby_ids:
        lobby = db.session.get(Lobby, lobby_id)
        if lobby:
            broadcast_lobby(lobby)
    return jsonify({
        "user_id": user.id,
        "username": user.username,
        "display_name": display_name,
    })


@app.get("/admin/lobbies")
@jwt_required()
def admin_lobbies():
    if not is_admin_user(int(get_jwt_identity())):
        return jsonify({"message": "Admin access required."}), 403

    return jsonify({"lobbies": admin_lobby_rows()})


@app.delete("/admin/lobbies/<code>")
@jwt_required()
def admin_close_lobby(code):
    if not is_admin_user(int(get_jwt_identity())):
        return jsonify({"message": "Admin access required."}), 403

    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    lobby_code = lobby.code
    delete_lobby_data(lobby)
    db.session.commit()
    broadcast_lobby_closed(lobby_code, "This lobby was closed by an administrator.")
    return jsonify({"message": "Lobby closed."})


@app.delete("/lobbies/<code>/leave")
@jwt_required()
def leave_lobby(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    player = Player.query.filter_by(lobby_id=lobby.id, user_id=user_id).first()
    bidder = Bidder.query.filter_by(lobby_id=lobby.id, user_id=user_id).first()
    if not player and not bidder:
        return jsonify({"message": "You are not in this lobby."}), 404

    was_host = lobby.host_user_id == user_id
    if player:
        db.session.delete(player)
    if bidder:
        db.session.delete(bidder)
    db.session.flush()

    next_host = None
    if was_host:
        remaining_players = Player.query.filter_by(lobby_id=lobby.id).all()
        if remaining_players:
            next_host = random.choice(remaining_players)
            lobby.host_user_id = next_host.user_id
        else:
            remaining_bidders = Bidder.query.filter_by(lobby_id=lobby.id).all()
            if remaining_bidders:
                next_host = random.choice(remaining_bidders)
                lobby.host_user_id = next_host.user_id

    has_players = Player.query.filter_by(lobby_id=lobby.id).count() > 0
    has_bidders = Bidder.query.filter_by(lobby_id=lobby.id).count() > 0
    if not has_players and not has_bidders:
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
        started_at=utc_now() + timedelta(seconds=INSTRUCTION_DURATION),
        typing_prompt=pick_prompt(),
    )
    db.session.add(session)
    db.session.flush()
    db.session.add(GameControl(
        game_session_id=session.id,
        round_index=0,
        phase="instructions",
        round_started_at=session.started_at,
        betting_settled=False,
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

    game_order = game_order_for(lobby)
    if control.round_index >= len(game_order) - 1:
        control.phase = "finished"
    else:
        start_betting_phase(lobby, control, control.round_index + 1)

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


@app.post("/lobbies/<code>/game/bets")
@jwt_required()
def place_game_bet(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    bidder = Bidder.query.filter_by(lobby_id=lobby.id, user_id=user_id).first()
    if not bidder:
        return jsonify({"message": "Only bidders can place bets."}), 403

    session = GameSession.query.filter_by(lobby_id=lobby.id).first()
    if not session:
        return jsonify({"message": "The game has not started."}), 409

    control = game_control(session)
    sync_game_control(lobby, session, control)
    if control.phase != "betting":
        return jsonify({"message": "Betting is closed for this round."}), 409

    data = request.get_json(silent=True) or {}
    try:
        player_user_id = int(data.get("player_user_id"))
        amount = Decimal(str(data.get("amount")))
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError
        amount_cents = int(amount * 100)
    except (InvalidOperation, TypeError, ValueError):
        return jsonify({"message": "Enter a positive bet with no more than two decimal places."}), 400

    player = Player.query.filter_by(lobby_id=lobby.id, user_id=player_user_id).first()
    if not player:
        return jsonify({"message": "Choose a current player."}), 400
    if amount_cents > bidder.balance_cents:
        return jsonify({"message": "Your bet exceeds your available balance."}), 400

    existing = Bet.query.filter_by(
        game_session_id=session.id,
        bidder_user_id=user_id,
        round_index=control.round_index,
    ).first()
    if existing:
        return jsonify({"message": "You already placed a bet this round."}), 409

    bidder.balance_cents -= amount_cents
    db.session.add(Bet(
        game_session_id=session.id,
        bidder_user_id=user_id,
        player_user_id=player_user_id,
        round_index=control.round_index,
        amount_cents=amount_cents,
    ))
    db.session.commit()
    broadcast_game(lobby, session)
    return jsonify({
        "message": "Bet placed.",
        "balance": bidder.balance_cents / 100,
        "betting": betting_payload(lobby, session, control),
    }), 201


@app.post("/lobbies/<code>/game/progress")
@jwt_required()
def update_game_progress(code):
    lobby = find_lobby(code)
    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    user_id = int(get_jwt_identity())
    if lobby_membership(lobby.id, user_id) != "player":
        return jsonify({"message": "Only players can report progress."}), 403

    recorded = record_live_progress(lobby, user_id, request.get_json(silent=True) or {})
    if not recorded:
        return jsonify({"message": "That round is not accepting progress."}), 409

    session, control = recorded
    payload = live_progress_payload(lobby, session, control)
    socketio.emit("game:progress", payload, room=bidder_room(lobby.code))
    return jsonify(payload)


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
    game_order = game_order_for(lobby)
    if (
        submitted_round < 0
        or submitted_round >= len(game_order)
        or submitted_round > state["round_index"]
        or (
            submitted_round == state["round_index"]
            and state["phase"] not in ("running", "settling", "leaderboard")
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
        state.get("elapsed_seconds", lobby.round_duration)
        if submitted_round == state["round_index"]
        else lobby.round_duration
    )
    elapsed = min(lobby.round_duration, max(0.01, elapsed))
    game_type = game_order[submitted_round]
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
        settle_round_bets(lobby, session, control)
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
