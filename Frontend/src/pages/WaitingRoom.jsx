import { useCallback, useEffect, useRef, useState } from "react";
import GameSequence from "./GameSequence";
import { useLobbySocket } from "../hooks/useLobbySocket";

const GAME_STATE_INTERVAL_MS = 1000;
const BIDDER_GAME_STATE_INTERVAL_MS = 5000;
const PROGRESS_TRAIL_INTERVAL_MS = 5000;

function WaitingRoom({ lobby: initialLobby, onExit, user }) {
  const [lobby, setLobby] = useState(initialLobby);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [exiting, setExiting] = useState(false);
  const [liveProgress, setLiveProgress] = useState(null);
  const progressTrailUpdate = useRef({ roundIndex: null, updatedAt: 0 });
  const bidderGameStateUpdateAt = useRef(0);
  const isBidderView = lobby.role === "bidder"
    || lobby.bidders?.some((bidder) => bidder.user_id === user.user_id);

  const updateProgressTrail = useCallback((progress) => {
    if (!progress) {
      progressTrailUpdate.current = { roundIndex: null, updatedAt: 0 };
      setLiveProgress(null);
      return;
    }

    const now = Date.now();
    const previous = progressTrailUpdate.current;
    if (
      previous.roundIndex !== progress.round_index
      || now - previous.updatedAt >= PROGRESS_TRAIL_INTERVAL_MS
    ) {
      progressTrailUpdate.current = {
        roundIndex: progress.round_index,
        updatedAt: now,
      };
      setLiveProgress(progress);
    }
  }, []);

  useEffect(() => {
    const phase = lobby.game?.phase;
    if (!lobby.code || !phase || !["instructions", "betting", "countdown", "running", "settling"].includes(phase)) {
      return undefined;
    }

    let cancelled = false;

    async function pollGameState() {
      try {
        const response = await fetch(`/lobbies/${lobby.code}/game`, {
          credentials: "include",
        });
        if (cancelled || !response.ok) {
          return;
        }
        const game = await response.json();
        if (cancelled) {
          return;
        }
        if (isBidderView) {
          bidderGameStateUpdateAt.current = Date.now();
        }
        setLobby((current) => ({ ...current, game }));
        updateProgressTrail(game.phase === "running" ? game.live_progress : null);
      } catch {
        // Socket updates or the next poll will retry.
      }
    }

    pollGameState();
    // Keep timers and phase transitions smooth even while Socket.IO reconnects.
    const intervalId = window.setInterval(
      pollGameState,
      isBidderView ? BIDDER_GAME_STATE_INTERVAL_MS : GAME_STATE_INTERVAL_MS,
    );
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [
    isBidderView,
    lobby.code,
    lobby.game?.phase,
    lobby.game?.round_index,
    updateProgressTrail,
  ]);

  useLobbySocket(lobby.code, {
    onLobbyUpdated: (data) => {
      const isPlayer = data.players?.some((player) => player.user_id === user.user_id);
      const isBidder = data.bidders?.some((bidder) => bidder.user_id === user.user_id);

      if (!isPlayer && !isBidder) {
        setExiting(true);
        onExit("You are no longer in this lobby.");
        return;
      }

      const role = isBidder
        ? "bidder"
        : data.host_user_id === user.user_id
          ? "host"
          : "player";

      setLobby((current) => ({ ...current, ...data, role }));
      setMessage("");
    },
    onGameState: (game) => {
      const now = Date.now();
      if (
        isBidderView
        && now - bidderGameStateUpdateAt.current < BIDDER_GAME_STATE_INTERVAL_MS
      ) {
        return;
      }
      if (isBidderView) {
        bidderGameStateUpdateAt.current = now;
      }
      setLobby((current) => ({ ...current, game }));
      updateProgressTrail(game.phase === "running" ? game.live_progress : null);
      setMessage("");
    },
    onGameProgress: (progress) => {
      updateProgressTrail(progress);
    },
    onClosed: (data) => {
      setExiting(true);
      onExit(data.message || "Lobby closed.");
    },
    onError: () => {
      setMessage("Live connection interrupted. Retrying...");
    },
  });

  const sendGameProgress = useCallback((progress) => {
    fetch(`/lobbies/${lobby.code}/game/progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(progress),
    }).catch(() => {
      // The next throttled update retries automatically.
    });
  }, [lobby.code]);

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
        isBidder={isBidderView}
        liveProgress={liveProgress}
        onLeave={leaveLobby}
        onProgress={sendGameProgress}
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
            <h2>Lobby</h2>
            <span>{(lobby.players?.length || 0) + (lobby.bidders?.length || 0)} / {lobby.lobby_limit}</span>
          </div>
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

          {(lobby.bidders?.length || 0) > 0 && (
            <>
              <div className="roster-heading bidder-heading">
                <h2>Bidders</h2>
                <span>{lobby.bidders.length} / {lobby.bidder_limit}</span>
              </div>
              <div className="player-list">
                {lobby.bidders.map((bidder) => (
                  <div className="player-row muted" key={bidder.user_id}>
                    <span className="player-dot" />
                    <strong>{bidder.name}</strong>
                    <span className="player-role">bidder</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <aside className="round-order-panel">
          <p className="status-kicker">Race order</p>
          <ol>
            <li><span>01</span> Typing × {lobby.typing_rounds || 1}</li>
            <li><span>02</span> Clicking × {lobby.clicking_rounds || 1}</li>
            <li><span>03</span> Spacebar × {lobby.spacebar_rounds || 1}</li>
          </ol>
          <p className="round-duration-copy">{lobby.round_duration || 30} seconds per round</p>
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
