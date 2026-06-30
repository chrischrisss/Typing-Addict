import eventlet

eventlet.monkey_patch()

from app import app  # noqa: E402
