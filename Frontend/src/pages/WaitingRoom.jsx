import { useState } from "react";
import GameSequence from "./GameSequence";
import { useLobbySocket } from "../hooks/useLobbySocket";

function WaitingRoom({ lobby: initialLobby, onExit, user }) {
  const [lobby, setLobby] = useState(initialLobby);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [exiting, setExiting] = useState(false);

  useLobbySocket(lobby.code, {
    onLobbyUpdated: (data) => {
      const isPlayer = data.players?.some((player) => player.user_id === user.user_id);
      const isViewer = data.viewers?.some((viewer) => viewer.user_id === user.user_id);

      if (!isPlayer && !isViewer) {
        setExiting(true);
        onExit("You are no longer in this lobby.");
        return;
      }

      const role = isViewer
        ? "viewer"
        : data.host_user_id === user.user_id
          ? "host"
          : "player";

      setLobby((current) => ({ ...current, ...data, role }));
      setMessage("");
    },
    onGameState: (game) => {
      setLobby((current) => ({ ...current, game }));
      setMessage("");
    },
    onClosed: (data) => {
      setExiting(true);
      onExit(data.message || "Lobby closed.");
    },
    onError: () => {
      setMessage("Live connection interrupted. Retrying...");
    },
  });

  async function leaveLobby() {
    setLoading(true);
    try {
      await fetch(`/lobbies/${lobby.code}/leave`, {
        method: "DELETE",
        credentials: "include",
      });
    } finally {
      onExit("You left the lobby.");
    }
  }

  async function kickPlayer(player) {
    setMessage("");
    const response = await fetch(`/lobbies/${lobby.code}/players/${player.user_id}`, {
      method: "DELETE",
      credentials: "include",
    });
    const data = await response.json();
    if (!response.ok) {
      setMessage(data.message || "Could not kick that player.");
    }
  }

  async function startGame() {
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`/lobbies/${lobby.code}/start`, {
        method: "POST",
        credentials: "include",
      });
      const data = await response.json();
      if (!response.ok) {
        setMessage(data.message || "Could not start the game.");
        return;
      }
      setLobby((current) => ({ ...current, game: data }));
    } catch {
      setMessage("Could not connect to the server.");
    } finally {
      setLoading(false);
    }
  }

  if (exiting) {
    return null;
  }

  if (lobby.game) {
    return (
      <GameSequence
        code={lobby.code}
        game={lobby.game}
        isViewer={lobby.role === "viewer"}
        onLeave={leaveLobby}
        user={user}
      />
    );
  }

  const isHost = lobby.host_user_id === user.user_id;

  return (
    <main className="waiting-page page-enter">
      <div className="lobby-speed-lines" aria-hidden="true" />
      <header className="waiting-header">
        <div>
          <p className="eyebrow">Waiting lobby · {lobby.code}</p>
          <h1>{lobby.name}</h1>
        </div>
        <button className="danger-button" type="button" disabled={loading} onClick={leaveLobby}>
          Leave lobby
        </button>
      </header>

      <section className="waiting-content">
        <div className="roster-panel">
          <div className="roster-heading">
            <h2>Players</h2>
            <span>{lobby.players?.length || 0} / {lobby.player_limit}</span>
          </div>
          <div className="player-list">
            {lobby.players?.map((player) => (
              <div className="player-row" key={player.user_id}>
                <span className="player-dot" />
                <strong>{player.name}</strong>
                <span className="player-role">{player.role}</span>
                {isHost && player.user_id !== user.user_id && (
                  <button type="button" onClick={() => kickPlayer(player)}>Kick</button>
                )}
              </div>
            ))}
          </div>

          {(lobby.viewers?.length || 0) > 0 && (
            <>
              <div className="roster-heading viewer-heading">
                <h2>Viewers</h2>
                <span>{lobby.viewers.length} / {lobby.viewer_limit}</span>
              </div>
              <div className="player-list">
                {lobby.viewers.map((viewer) => (
                  <div className="player-row muted" key={viewer.user_id}>
                    <span className="player-dot" />
                    <strong>{viewer.name}</strong>
                    <span className="player-role">viewer</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <aside className="round-order-panel">
          <p className="status-kicker">Race order</p>
          <ol>
            <li><span>01</span> Typing</li>
            <li><span>02</span> Clicking</li>
            <li><span>03</span> Spacebar</li>
          </ol>
          {isHost ? (
            <button className="login-button start-game-button" type="button" disabled={loading} onClick={startGame}>
              {loading ? "Starting..." : "Start game"}
            </button>
          ) : (
            <p className="waiting-copy">Waiting for the host to start the race.</p>
          )}
          <p className="form-message" role="status">{message}</p>
        </aside>
      </section>
    </main>
  );
}

export default WaitingRoom;
