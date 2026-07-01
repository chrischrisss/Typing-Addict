import os
import tempfile
import unittest
from datetime import timedelta


TEST_DIRECTORY = tempfile.mkdtemp(prefix="typing-addict-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(TEST_DIRECTORY, 'test.sqlite3')}"

from app import INSTRUCTION_DURATION, LIVE_PROGRESS, app, socketio, utc_now  # noqa: E402
from models import Bet, GameControl, db  # noqa: E402


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
        bidder = app.test_client()
        self.register(host, "host-user", "Host Racer")
        self.register(player, "player-user", "Player Two")
        self.register(bidder, "bidder-user", "Race Bidder")

        created = host.post(
            "/lobbies",
            json={"name": "Test room", "lobby_limit": 4, "player_limit": 2, "bidder_limit": 2},
        )
        self.assertEqual(created.status_code, 201)
        lobby = created.get_json()
        code = lobby["code"]
        host_id = lobby["host_user_id"]

        joined = player.post(f"/lobbies/{code}/join", json={})
        self.assertEqual(joined.status_code, 200)
        player_id = next(row["user_id"] for row in joined.get_json()["players"] if row["name"] == "Player Two")
        bidder_joined = bidder.post(f"/lobbies/{code}/join", json={})
        self.assertEqual(bidder_joined.status_code, 200)
        self.assertEqual(bidder_joined.get_json()["role"], "bidder")

        roster = host.get(f"/lobbies/{code}").get_json()
        self.assertEqual({row["name"] for row in roster["players"]}, {"Host Racer", "Player Two"})
        self.assertEqual(player.post(f"/lobbies/{code}/start").status_code, 403)

        kicked = host.delete(f"/lobbies/{code}/players/{player_id}")
        self.assertEqual(kicked.status_code, 200)
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
        bidder_socket = socketio.test_client(
            app,
            flask_test_client=bidder,
            query_string=f"lobby={code}",
        )
        player_socket.get_received()
        bidder_socket.get_received()
        prompt = started.get_json()["prompt"]
        typed_length = max(1, len(prompt) // 2)
        progress_response = player.post(f"/lobbies/{code}/game/progress", json={
            "round_index": 0,
            "game_type": "typing",
            "typed": prompt[:typed_length],
        })
        self.assertEqual(progress_response.status_code, 200)
        bidder_events = bidder_socket.get_received()
        progress_event = next(event for event in bidder_events if event["name"] == "game:progress")
        self.assertEqual(progress_event["args"][0]["players"][0]["user_id"], player_id)
        first_progress = progress_event["args"][0]["players"][0]["progress"]
        self.assertGreater(first_progress, 0)
        next_response = player.post(f"/lobbies/{code}/game/progress", json={
            "round_index": 0,
            "game_type": "typing",
            "typed": prompt,
        })
        self.assertEqual(next_response.status_code, 200)
        next_events = bidder_socket.get_received()
        next_progress = next(event for event in next_events if event["name"] == "game:progress")
        self.assertGreater(next_progress["args"][0]["players"][0]["progress"], first_progress)
        polled_progress = bidder.get(f"/lobbies/{code}/game").get_json()["live_progress"]
        self.assertEqual(polled_progress["players"][0]["progress"], 100)
        self.assertFalse(any(event["name"] == "game:progress" for event in player_socket.get_received()))
        player_socket.disconnect()
        bidder_socket.disconnect()

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

    def test_player_roles_fill_before_bidders_and_custom_round_settings(self):
        host = app.test_client()
        first_guest = app.test_client()
        second_guest = app.test_client()
        third_guest = app.test_client()
        fourth_guest = app.test_client()
        fifth_guest = app.test_client()
        self.register(host, "settings-host", "Settings Host")
        self.register(first_guest, "settings-one", "Guest One")
        self.register(second_guest, "settings-two", "Guest Two")
        self.register(third_guest, "settings-three", "Guest Three")
        self.register(fourth_guest, "settings-four", "Guest Four")
        self.register(fifth_guest, "settings-five", "Guest Five")

        created = host.post("/lobbies", json={
            "name": "Custom race",
            "lobby_limit": 5,
            "player_limit": 4,
            "bidder_limit": 4,
            "typing_rounds": 2,
            "clicking_rounds": 3,
            "spacebar_rounds": 1,
            "round_duration": 45,
        })
        self.assertEqual(created.status_code, 201)
        code = created.get_json()["code"]

        first_join = first_guest.post(f"/lobbies/{code}/join", json={"role": "bidder"})
        second_join = second_guest.post(f"/lobbies/{code}/join", json={"role": "bidder"})
        third_join = third_guest.post(f"/lobbies/{code}/join", json={"role": "bidder"})
        fourth_join = fourth_guest.post(f"/lobbies/{code}/join", json={"role": "player"})
        fifth_join = fifth_guest.post(f"/lobbies/{code}/join", json={})

        self.assertEqual(first_join.get_json()["role"], "player")
        self.assertEqual(second_join.get_json()["role"], "player")
        self.assertEqual(third_join.get_json()["role"], "player")
        self.assertEqual(fourth_join.get_json()["role"], "bidder")
        self.assertEqual(fifth_join.status_code, 409)

        started = host.post(f"/lobbies/{code}/start")
        self.assertEqual(started.status_code, 201)
        game = started.get_json()
        self.assertEqual(game["game_order"], [
            "typing", "typing", "clicking", "clicking", "clicking", "spacebar",
        ])
        self.assertEqual(game["round_duration"], 45)

    def test_departed_player_keeps_name_in_leaderboard(self):
        host = app.test_client()
        player = app.test_client()
        self.register(host, "departure-host", "Host Racer")
        self.register(player, "departure-player", "Bing Bong")

        created = host.post("/lobbies", json={
            "name": "Departure race",
            "lobby_limit": 3,
            "player_limit": 2,
            "bidder_limit": 1,
        })
        code = created.get_json()["code"]
        joined = player.post(f"/lobbies/{code}/join", json={})
        player_id = next(
            row["user_id"] for row in joined.get_json()["players"] if row["name"] == "Bing Bong"
        )
        started = host.post(f"/lobbies/{code}/start")

        with app.app_context():
            control = GameControl.query.one()
            control.phase = "running"
            control.round_started_at = utc_now() - timedelta(seconds=5)
            db.session.commit()

        submitted = player.post(f"/lobbies/{code}/game/submit", json={
            "round_index": 0,
            "typed": started.get_json()["prompt"],
        })
        self.assertEqual(submitted.status_code, 201)
        self.assertEqual(player.delete(f"/lobbies/{code}/leave").status_code, 200)

        game = host.get(f"/lobbies/{code}/game").get_json()
        departed = next(row for row in game["standings"] if row["user_id"] == player_id)
        self.assertEqual(departed["name"], "Bing Bong (left)")
        departed_result = next(row for row in game["results"] if row["user_id"] == player_id)
        self.assertEqual(departed_result["name"], "Bing Bong (left)")

    def test_legacy_lobby_payload_is_still_accepted(self):
        host = app.test_client()
        self.register(host, "legacy-host", "Legacy Host")

        created = host.post("/lobbies", json={
            "name": "Legacy room",
            "player_limit": 4,
            "viewer_limit": 12,
        })

        self.assertEqual(created.status_code, 201)
        lobby = created.get_json()
        self.assertEqual(lobby["lobby_limit"], 16)
        self.assertEqual(lobby["player_limit"], 4)
        self.assertEqual(lobby["bidder_limit"], 12)

    def test_bids_pay_only_first_place_and_store_player_amount(self):
        host = app.test_client()
        player = app.test_client()
        first_bidder = app.test_client()
        second_bidder = app.test_client()
        losing_bidder = app.test_client()
        self.register(host, "bet-host", "Host Player")
        self.register(player, "bet-player", "Fast Player")
        self.register(first_bidder, "bet-one", "Bidder One")
        self.register(second_bidder, "bet-two", "Bidder Two")
        self.register(losing_bidder, "bet-three", "Bidder Three")

        created = host.post("/lobbies", json={
            "name": "Betting room",
            "lobby_limit": 5,
            "player_limit": 2,
            "bidder_limit": 3,
        })
        code = created.get_json()["code"]
        player_join = player.post(f"/lobbies/{code}/join", json={}).get_json()
        player_id = next(row["user_id"] for row in player_join["players"] if row["name"] == "Fast Player")
        first_join = first_bidder.post(f"/lobbies/{code}/join", json={}).get_json()
        first_id = next(row["user_id"] for row in first_join["bidders"] if row["name"] == "Bidder One")
        second_join = second_bidder.post(f"/lobbies/{code}/join", json={}).get_json()
        second_id = next(row["user_id"] for row in second_join["bidders"] if row["name"] == "Bidder Two")
        losing_join = losing_bidder.post(f"/lobbies/{code}/join", json={}).get_json()
        losing_id = next(row["user_id"] for row in losing_join["bidders"] if row["name"] == "Bidder Three")

        started = host.post(f"/lobbies/{code}/start").get_json()
        self.assertEqual(started["phase"], "instructions")
        self.assertEqual(started["seconds_remaining"], INSTRUCTION_DURATION)
        self.assertTrue(all(row["balance"] == 1000 for row in started["betting"]["bidders"]))
        self.assertEqual(first_bidder.post(f"/lobbies/{code}/game/bets", json={
            "player_user_id": player_id,
            "amount": "100.00",
        }).status_code, 409)

        with app.app_context():
            control = GameControl.query.one()
            control.round_started_at = utc_now()
            db.session.commit()

        betting = host.get(f"/lobbies/{code}/game").get_json()
        self.assertEqual(betting["phase"], "betting")

        self.assertEqual(first_bidder.post(f"/lobbies/{code}/game/bets", json={
            "player_user_id": player_id,
            "amount": "100.00",
        }).status_code, 201)
        self.assertEqual(second_bidder.post(f"/lobbies/{code}/game/bets", json={
            "player_user_id": player_id,
            "amount": "200.00",
        }).status_code, 201)
        self.assertEqual(losing_bidder.post(f"/lobbies/{code}/game/bets", json={
            "player_user_id": created.get_json()["host_user_id"],
            "amount": "1000.00",
        }).status_code, 201)

        placed = host.get(f"/lobbies/{code}/game").get_json()["betting"]["bets"]
        self.assertEqual(
            {
                (bet["bidder_user_id"], bet["player_user_id"], bet["amount"])
                for bet in placed
            },
            {
                (first_id, player_id, 100),
                (second_id, player_id, 200),
                (losing_id, created.get_json()["host_user_id"], 1000),
            },
        )
        with app.app_context():
            stored_bets = Bet.query.order_by(Bet.bidder_user_id).all()
            self.assertEqual(
                {
                    (bet.bidder_user_id, bet.player_user_id, bet.amount_cents)
                    for bet in stored_bets
                },
                {
                    (first_id, player_id, 10000),
                    (second_id, player_id, 20000),
                    (losing_id, created.get_json()["host_user_id"], 100000),
                },
            )

        with app.app_context():
            control = GameControl.query.one()
            control.phase = "running"
            control.round_started_at = utc_now() - timedelta(seconds=31)
            db.session.commit()

        finalizing = host.get(f"/lobbies/{code}/game").get_json()
        self.assertEqual(finalizing["phase"], "settling")
        self.assertFalse(finalizing["betting"]["settled"])

        self.assertEqual(host.post(f"/lobbies/{code}/game/submit", json={
            "round_index": 0,
            "typed": "",
        }).status_code, 201)
        completed = player.post(f"/lobbies/{code}/game/submit", json={
            "round_index": 0,
            "typed": started["prompt"],
        })
        self.assertEqual(completed.status_code, 201)

        game = host.get(f"/lobbies/{code}/game").get_json()
        self.assertEqual(game["phase"], "leaderboard")
        self.assertEqual(game["betting"]["pot"], 1300)
        self.assertEqual({winner["user_id"] for winner in game["betting"]["winners"]}, {first_id, second_id})
        payouts = {winner["user_id"]: winner["payout"] for winner in game["betting"]["winners"]}
        self.assertEqual(payouts, {first_id: 433.33, second_id: 866.67})
        balances = {row["user_id"]: row["balance"] for row in game["betting"]["bidders"]}
        self.assertEqual(balances[first_id], 1333.33)
        self.assertEqual(balances[second_id], 1666.67)
        self.assertEqual(balances[losing_id], 0)
        with app.app_context():
            losing_bet = Bet.query.filter_by(bidder_user_id=losing_id).one()
            self.assertFalse(losing_bet.won)
            self.assertEqual(losing_bet.payout_cents, 0)
        self.assertEqual(
            [row["user_id"] for row in game["bidder_standings"]],
            [second_id, first_id, losing_id],
        )

        next_round = host.post(f"/lobbies/{code}/next").get_json()
        self.assertEqual(next_round["phase"], "betting")
        next_balances = {
            row["user_id"]: row["balance"] for row in next_round["betting"]["bidders"]
        }
        self.assertEqual(next_balances[losing_id], 50)

        # A sole correct bidder can only receive the money available in the pot.
        self.assertEqual(losing_bidder.post(f"/lobbies/{code}/game/bets", json={
            "player_user_id": player_id,
            "amount": "50.00",
        }).status_code, 201)
        with app.app_context():
            control = GameControl.query.one()
            control.phase = "running"
            control.round_started_at = utc_now()
            db.session.commit()

        self.assertEqual(host.post(f"/lobbies/{code}/game/submit", json={
            "round_index": 1,
            "count": 0,
        }).status_code, 201)
        self.assertEqual(player.post(f"/lobbies/{code}/game/submit", json={
            "round_index": 1,
            "count": 100,
        }).status_code, 201)
        solo_result = host.get(f"/lobbies/{code}/game").get_json()
        self.assertEqual(solo_result["betting"]["pot"], 50)
        self.assertEqual(solo_result["betting"]["winners"][0]["payout"], 50)
        solo_balances = {
            row["user_id"]: row["balance"] for row in solo_result["betting"]["bidders"]
        }
        self.assertEqual(solo_balances[losing_id], 50)

        # A player without a submitted result is not a winner, and a late
        # result cannot alter betting after settlement.
        third_round = host.post(f"/lobbies/{code}/next").get_json()
        self.assertEqual(third_round["phase"], "betting")
        self.assertEqual(losing_bidder.post(f"/lobbies/{code}/game/bets", json={
            "player_user_id": created.get_json()["host_user_id"],
            "amount": "50.00",
        }).status_code, 201)
        with app.app_context():
            control = GameControl.query.one()
            control.phase = "running"
            control.round_started_at = utc_now()
            db.session.commit()

        self.assertEqual(player.post(f"/lobbies/{code}/game/submit", json={
            "round_index": 2,
            "count": 100,
        }).status_code, 201)
        with app.app_context():
            control = GameControl.query.one()
            control.phase = "settling"
            control.round_started_at = utc_now() - timedelta(seconds=1)
            db.session.commit()

        settled = host.get(f"/lobbies/{code}/game").get_json()
        self.assertEqual(settled["phase"], "leaderboard")
        self.assertEqual(settled["betting"]["winners"], [])
        self.assertEqual(host.post(f"/lobbies/{code}/game/submit", json={
            "round_index": 2,
            "count": 1000,
        }).status_code, 409)

        finished = host.post(f"/lobbies/{code}/next").get_json()
        self.assertEqual(finished["phase"], "finished")
        self.assertEqual(
            [row["user_id"] for row in finished["bidder_standings"]],
            [second_id, first_id, losing_id],
        )

        self.assertEqual(host.delete(f"/lobbies/{code}/leave").status_code, 200)
        self.assertEqual(player.delete(f"/lobbies/{code}/leave").status_code, 200)
        bidder_host_lobby = first_bidder.get(f"/lobbies/{code}").get_json()
        self.assertEqual(bidder_host_lobby["players"], [])
        self.assertEqual(
            {row["user_id"] for row in bidder_host_lobby["bidders"]},
            {first_id, second_id, losing_id},
        )
        self.assertIn(bidder_host_lobby["host_user_id"], {first_id, second_id, losing_id})

    def test_admin_manages_users_and_lobbies_without_player_access(self):
        admin = app.test_client()
        host = app.test_client()
        self.register(admin, "admin", "Site Admin")
        self.register(host, "lobby-host", "Original Name")

        created = host.post("/lobbies", json={
            "name": "Admin test room",
            "lobby_limit": 8,
            "player_limit": 4,
            "bidder_limit": 4,
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
            "lobby_limit": 8,
            "player_limit": 4,
            "bidder_limit": 4,
        }).status_code, 403)

        closed = admin.delete(f"/admin/lobbies/{code}")
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(host.get(f"/lobbies/{code}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
