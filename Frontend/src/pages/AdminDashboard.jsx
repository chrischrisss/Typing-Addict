import { useCallback, useEffect, useState } from "react";

async function readJson(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("Admin API is unavailable. Restart the frontend and backend servers.");
  }
  return response.json();
}

function AdminDashboard({ handleLogout, user }) {
  const [users, setUsers] = useState([]);
  const [lobbies, setLobbies] = useState([]);
  const [draftNames, setDraftNames] = useState({});
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("users");

  const loadDashboard = useCallback(async () => {
    const response = await fetch("/admin/dashboard", { credentials: "include" });
    const data = await readJson(response);
    if (!response.ok) throw new Error(data.message || "Could not load dashboard data.");
    if (!Array.isArray(data.users) || !Array.isArray(data.lobbies)) {
      throw new Error("The admin API returned incomplete dashboard data.");
    }
    setUsers(data.users);
    setLobbies(data.lobbies);
    setDraftNames((current) => Object.fromEntries(data.users.map((account) => [
      account.user_id,
      current[account.user_id] ?? account.display_name,
    ])));
  }, []);

  useEffect(() => {
    let active = true;

    const initialLoad = window.setTimeout(() => {
      loadDashboard()
        .catch((error) => {
          if (active) setMessage(error.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 0);

    const interval = window.setInterval(() => {
      loadDashboard().catch(() => {});
    }, 3000);

    return () => {
      active = false;
      window.clearTimeout(initialLoad);
      window.clearInterval(interval);
    };
  }, [loadDashboard]);

  async function saveDisplayName(account) {
    const displayName = (draftNames[account.user_id] || "").trim();
    setMessage("");
    try {
      const response = await fetch(`/admin/users/${account.user_id}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ display_name: displayName }),
      });
      const data = await readJson(response);
      if (!response.ok) {
        setMessage(data.message || "Could not update that name.");
        return;
      }
      setUsers((current) => current.map((item) => (
        item.user_id === account.user_id ? { ...item, display_name: data.display_name } : item
      )));
      setMessage(`${account.username}'s in-game name was updated.`);
    } catch {
      setMessage("Could not connect to the server.");
    }
  }

  async function closeLobby(lobby) {
    if (!window.confirm(`Close ${lobby.name} (${lobby.code})?`)) return;

    setMessage("");
    try {
      const response = await fetch(`/admin/lobbies/${lobby.code}`, {
        method: "DELETE",
        credentials: "include",
      });
      const data = await readJson(response);
      if (!response.ok) {
        setMessage(data.message || "Could not close that lobby.");
        return;
      }
      setLobbies((current) => current.filter((item) => item.code !== lobby.code));
      setMessage(`${lobby.name} was closed.`);
    } catch {
      setMessage("Could not connect to the server.");
    }
  }

  return (
    <main className="admin-page">
      <div className="lobby-speed-lines" aria-hidden="true" />
      <header className="admin-header">
        <div>
          <p className="eyebrow">System administration</p>
          <h1>Admin console</h1>
          <p>Signed in as {user.username}</p>
        </div>
        <button className="danger-button" type="button" onClick={handleLogout}>Sign out</button>
      </header>

      <p className="admin-message" role="status">{loading ? "Loading dashboard..." : message}</p>

      <div className="admin-tabs" role="tablist" aria-label="Admin data">
        <button
          className={activeTab === "users" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "users"}
          onClick={() => setActiveTab("users")}
        >
          All users <span>{users.length}</span>
        </button>
        <button
          className={activeTab === "lobbies" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "lobbies"}
          onClick={() => setActiveTab("lobbies")}
        >
          Hosted lobbies <span>{lobbies.length}</span>
        </button>
      </div>

      <div className="admin-table-wrap">
        {activeTab === "users" && (
        <section className="admin-panel" aria-labelledby="accounts-heading">
          <div className="admin-panel-heading">
            <div>
              <p className="status-kicker">Accounts</p>
              <h2 id="accounts-heading">All users</h2>
            </div>
            <span>{users.length}</span>
          </div>
          <div className="admin-list">
            {users.length > 0 ? users.map((account) => (
              <div className="admin-user-row" key={account.user_id}>
                <div className="admin-user-identity">
                  <strong>{account.username}</strong>
                  <small>{account.is_admin ? "Administrator" : "User account"}</small>
                </div>
                <input
                  aria-label={`In-game name for ${account.username}`}
                  maxLength="18"
                  placeholder="No in-game name"
                  value={draftNames[account.user_id] || ""}
                  onChange={(event) => setDraftNames((current) => ({
                    ...current,
                    [account.user_id]: event.target.value,
                  }))}
                />
                <button type="button" onClick={() => saveDisplayName(account)}>Save</button>
              </div>
            )) : (
              <p className="admin-empty">No user accounts returned by the server.</p>
            )}
          </div>
        </section>
        )}

        {activeTab === "lobbies" && (
        <section className="admin-panel" aria-labelledby="lobbies-heading">
          <div className="admin-panel-heading">
            <div>
              <p className="status-kicker">Live rooms</p>
              <h2 id="lobbies-heading">Hosted lobbies</h2>
            </div>
            <span>{lobbies.length}</span>
          </div>
          <div className="admin-list">
            {lobbies.length > 0 ? lobbies.map((lobby) => (
              <div className="admin-lobby-row" key={lobby.code}>
                <div>
                  <strong>{lobby.name}</strong>
                  <small>{lobby.code} · Hosted by {lobby.host_name} (@{lobby.host_username})</small>
                </div>
                <span>{lobby.player_count} / {lobby.player_limit} players</span>
                <button type="button" onClick={() => closeLobby(lobby)}>Close</button>
              </div>
            )) : (
              <p className="admin-empty">No active lobbies.</p>
            )}
          </div>
        </section>
        )}
      </div>
    </main>
  );
}

export default AdminDashboard;
