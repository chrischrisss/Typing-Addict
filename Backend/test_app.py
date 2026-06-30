import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch


TEST_DIRECTORY = tempfile.mkdtemp(prefix="typing-addict-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(TEST_DIRECTORY, 'test.sqlite3')}"

from app import LIVE_PROGRESS, app, socketio, utc_now  # noqa: E402
from models import GameControl, db  # noqa: E402


class LobbyFlowTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
        LIVE_PROGRESS.clear()

    def register(self, client, username, display_name):
        response = client.post("/register", json={"username": username, "password": "password123"})
        self.assertEqual(response.status_code, 201)
        response = client.put("/me/profile", json={"display_name": display_name})
        self.assertEqual(response.status_code, 200)

    def test_waiting_room_host_transfer_and_three_rounds(self):
        host = app.test_client()
        player = app.test_client()
        viewer = app.test_client()
        self.register(host, "host-user", "Host Racer")
        self.register(player, "player-user", "Player Two")
        self.register(viewer, "viewer-user", "Race Watcher")

        created = host.post(
            "/lobbies",
            json={"name": "Test room", "player_limit": 4, "viewer_limit": 2},
        )
        self.assertEqual(created.status_code, 201)
        lobby = created.get_json()
        code = lobby["code"]
        host_id = lobby["host_user_id"]

        with patch("app.random.choice", side_effect=["player", "viewer"]):
            joined = player.post(f"/lobbies/{code}/join", json={})
            self.assertEqual(joined.status_code, 200)
            player_id = next(row["user_id"] for row in joined.get_json()["players"] if row["name"] == "Player Two")
            self.assertEqual(viewer.post(f"/lobbies/{code}/join", json={}).status_code, 200)

        roster = host.get(f"/lobbies/{code}").get_json()
        self.assertEqual({row["name"] for row in roster["players"]}, {"Host Racer", "Player Two"})
        self.assertEqual(player.post(f"/lobbies/{code}/start").status_code, 403)

        kicked = host.delete(f"/lobbies/{code}/players/{player_id}")
        self.assertEqual(kicked.status_code, 200)
        with patch("app.random.choice", return_value="player"):
            self.assertEqual(player.post(f"/lobbies/{code}/join", json={}).status_code, 200)

        left = host.delete(f"/lobbies/{code}/leave")
        self.assertEqual(left.status_code, 200)
        self.assertEqual(left.get_json()["host_user_id"], player_id)
        self.assertNotEqual(host_id, player_id)

        started = player.post(f"/lobbies/{code}/start")
        self.assertEqual(started.status_code, 201)
        self.assertEqual(started.get_json()["game_order"], ["typing", "clicking", "spacebar"])
        self.assertEqual(player.post(f"/lobbies/{code}/next").status_code, 409)

        with app.app_context():
            control = GameControl.query.one()
            control.phase = "running"
            control.round_started_at = utc_now() - timedelta(seconds=5)
            db.session.commit()

        player_socket = socketio.test_client(
            app,
            flask_test_client=player,
            query_string=f"lobby={code}",
        )
        viewer_socket = socketio.test_client(
            app,
            flask_test_client=viewer,
            query_string=f"lobby={code}",
        )
        player_socket.get_received()
        viewer_socket.get_received()
        prompt = started.get_json()["prompt"]
        typed_length = max(1, len(prompt) // 2)
        progress_response = player.post(f"/lobbies/{code}/game/progress", json={
            "round_index": 0,
            "game_type": "typing",
            "typed": prompt[:typed_length],
        })
        self.assertEqual(progress_response.status_code, 200)
        viewer_events = viewer_socket.get_received()
        progress_event = next(event for event in viewer_events if event["name"] == "game:progress")
        self.assertEqual(progress_event["args"][0]["players"][0]["user_id"], player_id)
        first_progress = progress_event["args"][0]["players"][0]["progress"]
        self.assertGreater(first_progress, 0)
        next_response = player.post(f"/lobbies/{code}/game/progress", json={
            "round_index": 0,
            "game_type": "typing",
            "typed": prompt,
        })
        self.assertEqual(next_response.status_code, 200)
        next_events = viewer_socket.get_received()
        next_progress = next(event for event in next_events if event["name"] == "game:progress")
        self.assertGreater(next_progress["args"][0]["players"][0]["progress"], first_progress)
        polled_progress = viewer.get(f"/lobbies/{code}/game").get_json()["live_progress"]
        self.assertEqual(polled_progress["players"][0]["progress"], 100)
        self.assertFalse(any(event["name"] == "game:progress" for event in player_socket.get_received()))
        player_socket.disconnect()
        viewer_socket.disconnect()

        typed = player.post(
            f"/lobbies/{code}/game/submit",
            json={"round_index": 0, "typed": prompt},
        )
        self.assertEqual(typed.status_code, 201)
        typing_board = player.get(f"/lobbies/{code}/game").get_json()
        self.assertEqual(typing_board["phase"], "leaderboard")
        self.assertGreater(typing_board["standings"][0]["round_score"], 0)
        self.assertEqual(host.post(f"/lobbies/{code}/next").status_code, 403)
        next_round = player.post(f"/lobbies/{code}/next")
        self.assertEqual(next_round.status_code, 200)
        self.assertEqual(next_round.get_json()["round_index"], 1)

        with app.app_context():
            control = GameControl.query.one()
            control.phase = "running"
            control.round_started_at = utc_now() - timedelta(seconds=5)
            db.session.commit()
        clicked = player.post(
            f"/lobbies/{code}/game/submit",
            json={"round_index": 1, "count": 30},
        )
        self.assertEqual(clicked.status_code, 201)
        self.assertEqual(player.post(f"/lobbies/{code}/next").get_json()["round_index"], 2)

        with app.app_context():
            control = GameControl.query.one()
            control.phase = "running"
            control.round_started_at = utc_now() - timedelta(seconds=5)
            db.session.commit()
        spacebar = player.post(
            f"/lobbies/{code}/game/submit",
            json={"round_index": 2, "count": 35},
        )
        self.assertEqual(spacebar.status_code, 201)
        finished = player.post(f"/lobbies/{code}/next")
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.get_json()["phase"], "finished")

    def test_random_roles_and_custom_round_settings(self):
        host = app.test_client()
        first_guest = app.test_client()
        second_guest = app.test_client()
        self.register(host, "settings-host", "Settings Host")
        self.register(first_guest, "settings-one", "Guest One")
        self.register(second_guest, "settings-two", "Guest Two")

        created = host.post("/lobbies", json={
            "name": "Custom race",
            "player_limit": 4,
            "viewer_limit": 4,
            "typing_rounds": 2,
            "clicking_rounds": 3,
            "spacebar_rounds": 1,
            "round_duration": 45,
        })
        self.assertEqual(created.status_code, 201)
        code = created.get_json()["code"]

        with patch("app.random.choice", side_effect=["viewer", "player"]):
            viewer_join = first_guest.post(f"/lobbies/{code}/join", json={"role": "player"})
            player_join = second_guest.post(f"/lobbies/{code}/join", json={"role": "viewer"})

        self.assertEqual(viewer_join.get_json()["role"], "viewer")
        self.assertEqual(player_join.get_json()["role"], "player")

        started = host.post(f"/lobbies/{code}/start")
        self.assertEqual(started.status_code, 201)
        game = started.get_json()
        self.assertEqual(game["game_order"], [
            "typing", "typing", "clicking", "clicking", "clicking", "spacebar",
        ])
        self.assertEqual(game["round_duration"], 45)

    def test_admin_manages_users_and_lobbies_without_player_access(self):
        admin = app.test_client()
        host = app.test_client()
        self.register(admin, "admin", "Site Admin")
        self.register(host, "lobby-host", "Original Name")

        created = host.post("/lobbies", json={
            "name": "Admin test room",
            "player_limit": 4,
            "viewer_limit": 4,
        })
        self.assertEqual(created.status_code, 201)
        code = created.get_json()["code"]

        users_response = admin.get("/admin/users")
        self.assertEqual(users_response.status_code, 200)
        accounts = users_response.get_json()["users"]
        host_account = next(account for account in accounts if account["username"] == "lobby-host")
        self.assertEqual(host_account["display_name"], "Original Name")

        renamed = admin.put(
            f"/admin/users/{host_account['user_id']}/profile",
            json={"display_name": "Renamed Racer"},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.get_json()["display_name"], "Renamed Racer")

        lobbies_response = admin.get("/admin/lobbies")
        self.assertEqual(lobbies_response.status_code, 200)
        lobby = lobbies_response.get_json()["lobbies"][0]
        self.assertEqual(lobby["host_username"], "lobby-host")
        self.assertEqual(lobby["host_name"], "Renamed Racer")
        self.assertEqual(lobby["player_count"], 1)
        dashboard = admin.get("/admin/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(len(dashboard.get_json()["users"]), 2)
        self.assertEqual(len(dashboard.get_json()["lobbies"]), 1)
        self.assertEqual(host.get("/admin/users").status_code, 403)

        self.assertEqual(admin.post(f"/lobbies/{code}/join", json={}).status_code, 403)
        self.assertEqual(admin.post("/lobbies", json={
            "name": "Forbidden room",
            "player_limit": 4,
            "viewer_limit": 4,
        }).status_code, 403)

        closed = admin.delete(f"/admin/lobbies/{code}")
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(host.get(f"/lobbies/{code}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
