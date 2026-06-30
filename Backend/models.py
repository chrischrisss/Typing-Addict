from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    display_name = db.Column(db.String(18), nullable=False)
    user = db.relationship("User", backref=db.backref("profile", uselist=False))

class Lobby(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False, index=True)
    name = db.Column(db.String(32), nullable=False)
    host_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    player_limit = db.Column(db.Integer, nullable=False)
    viewer_limit = db.Column(db.Integer, nullable=False)
    typing_rounds = db.Column(db.Integer, nullable=False, default=1)
    clicking_rounds = db.Column(db.Integer, nullable=False, default=1)
    spacebar_rounds = db.Column(db.Integer, nullable=False, default=1)
    round_duration = db.Column(db.Integer, nullable=False, default=30)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    host = db.relationship("User", backref="hosted_lobbies")
    players = db.relationship("Player", backref="lobby", lazy=True)
    viewers = db.relationship("Viewer", backref="lobby", lazy=True)

class Player(db.Model):
    __table_args__ = (db.UniqueConstraint("user_id", "lobby_id", name="uq_player_lobby_user"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='players')
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

class Viewer(db.Model):
    __table_args__ = (db.UniqueConstraint("user_id", "lobby_id", name="uq_viewer_lobby_user"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='viewers')
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class GameSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey("lobby.id"), unique=True, nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    typing_prompt = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class GameControl(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_session_id = db.Column(db.Integer, db.ForeignKey("game_session.id"), unique=True, nullable=False)
    round_index = db.Column(db.Integer, nullable=False, default=0)
    phase = db.Column(db.String(20), nullable=False, default="countdown")
    round_started_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())


class GameResult(db.Model):
    __table_args__ = (
        db.UniqueConstraint("game_session_id", "user_id", "round_index", name="uq_game_result"),
    )

    id = db.Column(db.Integer, primary_key=True)
    game_session_id = db.Column(db.Integer, db.ForeignKey("game_session.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    round_index = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    metric = db.Column(db.Integer, nullable=False, default=0)
    accuracy = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
