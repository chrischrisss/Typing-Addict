import eventlet

eventlet.monkey_patch()

from app import app, start_game_tick_loop  # noqa: E402

start_game_tick_loop()
