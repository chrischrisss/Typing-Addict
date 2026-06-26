import os

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

from models import User, db


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


if __name__ == "__main__":
    app.run(debug=True)