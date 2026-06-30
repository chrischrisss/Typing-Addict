import { useEffect, useState } from "react";
import Login from "./pages/Login";
import Lobby from "./pages/Lobby";
import AdminDashboard from "./pages/AdminDashboard";
import "./App.css";

function App() {
  const [user, setUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      try {
        const response = await fetch("/me", {
          credentials: "include",
        });

        if (response.ok && active) {
          setUser(await response.json());
        }
      } catch {
        if (active) {
          setUser(null);
        }
      } finally {
        if (active) {
          setCheckingSession(false);
        }
      }
    }

    restoreSession();

    return () => {
      active = false;
    };
  }, []);

  async function handleLogin(username, password) {
    if (!username.trim() || !password) {
      return { ok: false, message: "Enter your username and password." };
    }

    try {
      const response = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username: username.trim(), password }),
      });

      const data = await response.json();

      if (!response.ok) {
        return { ok: false, message: data.message || "Login failed." };
      }

      const userResponse = await fetch("/me", {
        credentials: "include",
      });

      if (!userResponse.ok) {
        return { ok: false, message: "Your session could not be loaded." };
      }

      setUser(await userResponse.json());
      return { ok: true, message: "" };
    } catch {
      return { ok: false, message: "Could not connect to the server." };
    }
  }

  async function handleRegister(username, password, confirmPassword) {
    if (!username.trim() || !password || !confirmPassword) {
      return { ok: false, message: "Fill out every field." };
    }

    if (password !== confirmPassword) {
      return { ok: false, message: "Passwords do not match." };
    }

    try {
      const response = await fetch("/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username: username.trim(), password }),
      });

      const data = await response.json();

      if (!response.ok) {
        return { ok: false, message: data.message || "Registration failed." };
      }

      const userResponse = await fetch("/me", {
        credentials: "include",
      });

      if (!userResponse.ok) {
        return { ok: false, message: "Your account was created, but the session failed." };
      }

      setUser(await userResponse.json());
      return { ok: true, message: "" };
    } catch {
      return { ok: false, message: "Could not connect to the server." };
    }
  }

  async function handleLogout() {
    try {
      await fetch("/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      setUser(null);
    }
  }

  if (user) {
    const activeUser = user.user ?? user;
    if (activeUser.username?.toLowerCase() === "admin") {
      return <AdminDashboard handleLogout={handleLogout} user={activeUser} />;
    }
    return <Lobby handleLogout={handleLogout} user={activeUser} />;
  }

  return (
    <Login
      checkingSession={checkingSession}
      handleLogin={handleLogin}
      handleLogout={handleLogout}
      handleRegister={handleRegister}
      user={user}
    />
  );
}

export default App;
