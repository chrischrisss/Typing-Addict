import unittest

from app import app
from models import User, db


class AuthTestCase(unittest.TestCase):
    username = "racefan"

    def setUp(self):
        self.client = app.test_client()
        self.remove_test_user()

    def tearDown(self):
        self.remove_test_user()

    def remove_test_user(self):
        with app.app_context():
            user = User.query.filter_by(username=self.username).first()
            if user:
                db.session.delete(user)
                db.session.commit()

    def test_register_login_and_logout(self):
        invalid = self.client.post(
            "/register",
            json={"username": "x", "password": "short"},
        )
        self.assertEqual(invalid.status_code, 400)

        created = self.client.post(
            "/register",
            json={"username": self.username, "password": "password123"},
        )
        self.assertEqual(created.status_code, 201)

        current_user = self.client.get("/me")
        self.assertEqual(current_user.status_code, 200)
        self.assertEqual(current_user.get_json()["username"], self.username)

        duplicate = self.client.post(
            "/register",
            json={"username": self.username, "password": "password123"},
        )
        self.assertEqual(duplicate.status_code, 409)

        self.assertEqual(self.client.post("/logout").status_code, 200)
        self.assertEqual(self.client.get("/me").status_code, 401)

        login = self.client.post(
            "/login",
            json={"username": self.username, "password": "password123"},
        )
        self.assertEqual(login.status_code, 200)


if __name__ == "__main__":
    unittest.main()
