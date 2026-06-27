import os
import random

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    unset_jwt_cookies,
)
from werkzeug.security import check_password_hash, generate_password_hash

from models import Lobby, Player, User, Viewer, db


CODE_CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


app = Flask(__name__)
CORS(app, supports_credentials=True)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite3"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.environ.get(
    "JWT_SECRET_KEY",
    "development-only-secret-change-before-production",
)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_COOKIE_SAMESITE"] = "Lax"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

db.init_app(app)
JWTManager(app)


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

    return jsonify({"user_id": user.id, "username": user.username})


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


def lobby_payload(lobby):
    player_count = Player.query.filter_by(lobby_id=lobby.id).count()
    viewer_count = Viewer.query.filter_by(lobby_id=lobby.id).count()

    return {
        "code": lobby.code,
        "name": lobby.name,
        "host_user_id": lobby.host_user_id,
        "player_limit": lobby.player_limit,
        "viewer_limit": lobby.viewer_limit,
        "player_count": player_count,
        "viewer_count": viewer_count,
    }


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

    return jsonify(lobby_payload(lobby)), 201


@app.get("/lobbies/<code>")
@jwt_required()
def get_lobby(code):
    clean_code = str(code).strip().upper()

    if len(clean_code) != 6:
        return jsonify({"message": "Lobby not found."}), 404

    lobby = Lobby.query.filter_by(code=clean_code).first()

    if not lobby:
        return jsonify({"message": "Lobby not found."}), 404

    return jsonify(lobby_payload(lobby))


if __name__ == "__main__":
    app.run(debug=True)