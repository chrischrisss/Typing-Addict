from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Lobby(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False, index=True)
    name = db.Column(db.String(32), nullable=False)
    host_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    player_limit = db.Column(db.Integer, nullable=False)
    viewer_limit = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    host = db.relationship("User", backref="hosted_lobbies")
    players = db.relationship("Player", backref="lobby", lazy=True)
    viewers = db.relationship("Viewer", backref="lobby", lazy=True)

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='players')
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

class Viewer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='viewers')
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
