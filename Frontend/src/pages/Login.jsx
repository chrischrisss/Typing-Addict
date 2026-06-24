import { useState } from "react";

function Login({ checkingSession, handleLogin, handleLogout, handleRegister, user }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submitForm(event) {
    event.preventDefault();
    setMessage("");
    setSubmitting(true);

    const result = mode === "login"
      ? await handleLogin(username, password)
      : await handleRegister(username, password, confirmPassword);

    setSubmitting(false);
    setMessage(result.message);

    if (result.ok) {
      setPassword("");
      setConfirmPassword("");
    }
  }

  function switchMode(nextMode) {
    setMode(nextMode);
    setPassword("");
    setConfirmPassword("");
    setMessage("");
  }

  return (
    <main className="login-page">
      <div className="race-lines" aria-hidden="true" />

      <div className="login-layout">
        <section className="brand-panel">
          <p className="brand-mark">TA</p>
          <p className="eyebrow">Typing Addict</p>
          <h1>Type fast.<br />Bet smart.</h1>
          <p className="tagline">Head-to-head typing races with real stakes.</p>
        </section>

        <section className="login-card" aria-labelledby="auth-title">
          {checkingSession ? (
            <p className="session-status" role="status">Checking session...</p>
          ) : user ? (
            <div className="signed-in">
              <p className="status-kicker">Signed in</p>
              <h2 id="auth-title">{user.username}</h2>
              <button className="secondary-button" type="button" onClick={handleLogout}>
                Sign out
              </button>
            </div>
          ) : (
            <>
              <p className="status-kicker">
                {mode === "login" ? "Welcome back" : "New challenger"}
              </p>
              <h2 id="auth-title">
                {mode === "login" ? "Sign in" : "Create account"}
              </h2>

              <form onSubmit={submitForm}>
                <label htmlFor="username">Username</label>
                <input
                  id="username"
                  name="username"
                  type="text"
                  autoComplete="username"
                  autoFocus
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />

                <label htmlFor="password">Password</label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />

                {mode === "register" && (
                  <>
                    <label htmlFor="confirm-password">Confirm password</label>
                    <input
                      id="confirm-password"
                      name="confirm-password"
                      type="password"
                      autoComplete="new-password"
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                    />
                  </>
                )}

                <button className="login-button" type="submit" disabled={submitting}>
                  {submitting
                    ? mode === "login" ? "Signing in..." : "Creating account..."
                    : mode === "login" ? "Enter the race floor" : "Join the race floor"}
                </button>

                <p className="form-message" role="status" aria-live="polite">
                  {message}
                </p>
              </form>

              <div className="auth-switch">
                <span>
                  {mode === "login" ? "Need an account?" : "Already have an account?"}
                </span>
                <button
                  type="button"
                  onClick={() => switchMode(mode === "login" ? "register" : "login")}
                >
                  {mode === "login" ? "Register" : "Sign in"}
                </button>
              </div>
            </>
          )}
        </section>
      </div>

      <p className="responsible-note">18+ only. Play responsibly.</p>
    </main>
  );
}

export default Login;
