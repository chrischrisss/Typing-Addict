import { useEffect, useMemo, useRef, useState } from "react";
import WaitingRoom from "./WaitingRoom";
import { useLobbySocket } from "../hooks/useLobbySocket";

const BLOCKED_NAME_TERMS = [
  "admin",
  "moderator",
  "owner",
  "staff",
  "support",
  "fuck",
  "shit",
  "bitch",
  "asshole",
  "slur",
];

const LEET_MAP = {
  0: "o",
  1: "i",
  3: "e",
  4: "a",
  5: "s",
  7: "t",
  "@": "a",
  "$": "s",
  "!": "i",
};

function normalizeName(value) {
  return value
    .toLowerCase()
    .replace(/[013457@$!]/g, (character) => LEET_MAP[character] || character)
    .replace(/[^a-z]/g, "");
}

function validateInGameName(value) {
  const trimmed = value.trim();

  if (trimmed.length < 3 || trimmed.length > 18) {
    return "Choose a name between 3 and 18 characters.";
  }

  if (!/^[a-zA-Z0-9 _-]+$/.test(trimmed)) {
    return "Use letters, numbers, spaces, underscores, or hyphens only.";
  }

  const normalized = normalizeName(trimmed);
  const blockedTerm = BLOCKED_NAME_TERMS.find((term) =>
    normalized.includes(normalizeName(term))
  );

  if (blockedTerm) {
    return "Choose a different name.";
  }

  return "";
}

function readInviteCode() {
  const params = new URLSearchParams(window.location.search);
  return params.get("lobby")?.trim().toUpperCase() || "";
}

function Lobby({ handleLogout, user }) {
  const storageKey = `typing-addict-ingame-name-${user.user_id}`;
  const [initialInviteCode] = useState(readInviteCode);
  const inviteCodeRef = useRef(initialInviteCode);
  const [savedName, setSavedName] = useState(
    () => localStorage.getItem(storageKey) || user.display_name || ""
  );
  const [draftName, setDraftName] = useState(savedName);
  const [profileOpen, setProfileOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [lobbyMode, setLobbyMode] = useState("home");
  const [joinCode, setJoinCode] = useState(initialInviteCode);
  const [joinRole, setJoinRole] = useState("player");
  const [joinMessage, setJoinMessage] = useState("");
  const [inviteNotice, setInviteNotice] = useState("");
  const [lobbyName, setLobbyName] = useState("");
  const [playerLimit, setPlayerLimit] = useState(4);
  const [viewerLimit, setViewerLimit] = useState(12);
  const [createMessage, setCreateMessage] = useState("");
  const [createdInvite, setCreatedInvite] = useState(null);
  const [joinLobbyInfo, setJoinLobbyInfo] = useState(null);
  const [activeGame, setActiveGame] = useState(null);

  const needsName = !savedName;
  const titleName = savedName || "Player";

  const initials = useMemo(() => {
    return titleName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0].toUpperCase())
      .join("") || "P";
  }, [titleName]);

  useEffect(() => {
    if (!inviteCodeRef.current) {
      return;
    }

    window.history.replaceState({}, "", window.location.pathname);
  }, []);

  useEffect(() => {
    const inviteCode = inviteCodeRef.current;

    if (!inviteCode || needsName) {
      return;
    }

    inviteCodeRef.current = "";

    let active = true;

    async function checkInvite() {
      try {
        const response = await fetch(`/lobbies/${inviteCode}`, {
          credentials: "include",
        });
        const data = await response.json();

        if (!active) {
          return;
        }

        if (!response.ok) {
          setInviteNotice("Lobby not found.");
          return;
        }

        setJoinLobbyInfo(data);
        setJoinCode(inviteCode);
        setLobbyMode("join");
        setJoinMessage(`${data.name} is open. Pick player or viewer and join.`);
      } catch {
        if (active) {
          setInviteNotice("Could not connect to the server.");
        }
      }
    }

    checkInvite();

    return () => {
      active = false;
    };
  }, [needsName]);

  useEffect(() => {
    if (lobbyMode !== "join") {
      return;
    }

    const cleanCode = joinCode.trim().toUpperCase();

    if (!/^[A-Z0-9]{6}$/.test(cleanCode) || !/[A-Z]/.test(cleanCode) || !/[0-9]/.test(cleanCode)) {
      return;
    }

    let active = true;

    async function loadLobbyInfo() {
      try {
        const response = await fetch(`/lobbies/${cleanCode}`, {
          credentials: "include",
        });
        const data = await response.json();

        if (!active) {
          return;
        }

        if (!response.ok) {
          setJoinLobbyInfo(null);
          return;
        }

        setJoinLobbyInfo(data);

        setJoinRole((current) => {
          if (data.player_count >= data.player_limit && current === "player") {
            if (data.viewer_count < data.viewer_limit && data.viewer_limit > 0) {
              return "viewer";
            }
          }

          if (data.viewer_count >= data.viewer_limit && current === "viewer") {
            if (data.player_count < data.player_limit) {
              return "player";
            }
          }

          return current;
        });
      } catch {
        if (active) {
          setJoinLobbyInfo(null);
        }
      }
    }

    loadLobbyInfo();

    return () => {
      active = false;
    };
  }, [lobbyMode, joinCode]);

  const createdInviteCode = createdInvite?.code;

  useLobbySocket(createdInviteCode, {
    onLobbyUpdated: (data) => {
      setCreatedInvite((current) => {
        if (!current) {
          return current;
        }

        return {
          ...current,
          playerCount: data.player_count,
          viewerCount: data.viewer_count,
        };
      });
    },
  });

  async function saveName(event) {
    event.preventDefault();
    const validationMessage = validateInGameName(draftName);

    if (validationMessage) {
      setMessage(validationMessage);
      return;
    }

    const cleanName = draftName.trim().replace(/\s+/g, " ");
    try {
      const response = await fetch("/me/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ display_name: cleanName }),
      });
      const data = await response.json();
      if (!response.ok) {
        setMessage(data.message || "Could not save your name.");
        return;
      }
    } catch {
      setMessage("Could not connect to the server.");
      return;
    }

    localStorage.setItem(storageKey, cleanName);
    setSavedName(cleanName);
    setDraftName(cleanName);
    setMessage("");
    setProfileOpen(false);
  }

  function openProfile() {
    setDraftName(savedName);
    setMessage("");
    setProfileOpen(true);
  }

  function openLobbyMode(nextMode) {
    setLobbyMode(nextMode);
    setJoinMessage("");
    setCreateMessage("");
    setCreatedInvite(null);
    setJoinLobbyInfo(null);
    setInviteNotice("");
  }

  const playersFull = joinLobbyInfo
    ? joinLobbyInfo.player_count >= joinLobbyInfo.player_limit
    : false;
  const viewersFull = joinLobbyInfo
    ? joinLobbyInfo.viewer_count >= joinLobbyInfo.viewer_limit || joinLobbyInfo.viewer_limit <= 0
    : false;

  async function submitJoinLobby(event) {
    event.preventDefault();
    const cleanCode = joinCode.trim().toUpperCase();

    if (!/^[A-Z0-9]{6}$/.test(cleanCode) || !/[A-Z]/.test(cleanCode) || !/[0-9]/.test(cleanCode)) {
      setJoinMessage("Enter a 6-character lobby code using letters and numbers.");
      return;
    }

    setJoinMessage("");

    try {
      const response = await fetch(`/lobbies/${cleanCode}/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ role: joinRole }),
      });
      const data = await response.json();

      if (!response.ok) {
        setJoinMessage(data.message || "Could not join lobby.");
        return;
      }

      setActiveGame(data);
    } catch {
      setJoinMessage("Could not connect to the server.");
    }
  }

  async function submitCreateLobby(event) {
    event.preventDefault();
    const cleanLobbyName = lobbyName.trim().replace(/\s+/g, " ");
    const players = Number(playerLimit);
    const viewers = Number(viewerLimit);

    if (cleanLobbyName.length < 3 || cleanLobbyName.length > 32) {
      setCreateMessage("Lobby name must be 3 to 32 characters.");
      return;
    }

    if (!Number.isInteger(players) || players < 2 || players > 12) {
      setCreateMessage("Player size must be between 2 and 12.");
      return;
    }

    if (!Number.isInteger(viewers) || viewers < 0 || viewers > 100) {
      setCreateMessage("Viewer size must be between 0 and 100.");
      return;
    }

    setCreateMessage("");

    try {
      const response = await fetch("/lobbies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: cleanLobbyName,
          player_limit: players,
          viewer_limit: viewers,
        }),
      });
      const data = await response.json();

      if (!response.ok) {
        setCreateMessage(data.message || "Could not create lobby.");
        return;
      }

      setCreatedInvite({
        code: data.code,
        link: `${window.location.origin}/?lobby=${data.code}`,
        name: data.name,
        players: data.player_limit,
        viewers: data.viewer_limit,
        playerCount: data.player_count,
        viewerCount: data.viewer_count,
      });
    } catch {
      setCreateMessage("Could not connect to the server.");
    }
  }

  function enterCreatedGame() {
    setActiveGame({
      code: createdInvite.code,
      name: createdInvite.name,
      role: "host",
    });
  }

  function exitActiveLobby(notice = "") {
    setActiveGame(null);
    setLobbyMode("home");
    setCreatedInvite(null);
    setInviteNotice(notice);
  }

  if (activeGame) {
    return <WaitingRoom lobby={activeGame} onExit={exitActiveLobby} user={user} />;
  }

  return (
    <main className="lobby-page">
      <div className="lobby-speed-lines" aria-hidden="true" />

      <header className="lobby-topbar">
        <button className="profile-button" type="button" onClick={openProfile}>
          <span className="profile-avatar">{initials}</span>
          <span>
            <span className="profile-label">Profile</span>
            <strong>Welcome {titleName}</strong>
          </span>
        </button>

        <button className="topbar-signout" type="button" onClick={handleLogout}>
          Sign out
        </button>
      </header>

      <section className="lobby-stage" aria-labelledby="lobby-title">
        {needsName ? (
          <div className="name-panel">
            <p className="status-kicker">First race setup</p>
            <h1 id="lobby-title">Set your in-game name</h1>
            <form onSubmit={saveName}>
              <label htmlFor="ingame-name">In-game name</label>
              <input
                id="ingame-name"
                type="text"
                autoFocus
                maxLength="18"
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
              />
              <button className="login-button" type="submit">
                Save name
              </button>
              <p className="form-message" role="status" aria-live="polite">
                {message}
              </p>
            </form>
          </div>
        ) : (
          <>
            <div className="lobby-heading">
              <p className="eyebrow">Main lobby</p>
              <h1 id="lobby-title">Race floor</h1>
            </div>

            {inviteNotice && (
              <p className="lobby-notice" role="status" aria-live="polite">
                {inviteNotice}
              </p>
            )}

            <div className="lobby-actions">
              <button type="button" onClick={() => openLobbyMode("join")}>
                <span>Join lobby</span>
                <small>Find an open race room</small>
              </button>
              <button type="button" onClick={() => openLobbyMode("create")}>
                <span>Create lobby</span>
                <small>Start a new race room</small>
              </button>
            </div>
          </>
        )}
      </section>

      {lobbyMode === "join" && (
        <div className="profile-modal" role="dialog" aria-modal="true" aria-labelledby="join-title">
          <form className="lobby-sheet" onSubmit={submitJoinLobby}>
            <p className="status-kicker">Join lobby</p>
            <h2 id="join-title">Enter lobby code</h2>
            <label htmlFor="join-code">6-character code</label>
            <input
              id="join-code"
              type="text"
              autoFocus
              maxLength="6"
              value={joinCode}
              onChange={(event) => {
                setJoinCode(event.target.value.toUpperCase());
                setJoinLobbyInfo(null);
              }}
              placeholder="A1B2C3"
            />
            <label htmlFor="join-role">Join as</label>
            <select
              id="join-role"
              value={joinRole}
              onChange={(event) => setJoinRole(event.target.value)}
            >
              <option value="player" disabled={playersFull}>
                Player
              </option>
              <option value="viewer" disabled={viewersFull}>
                Viewer
              </option>
            </select>
            {joinLobbyInfo && (
              <p className="invite-meta">
                {joinLobbyInfo.player_count} / {joinLobbyInfo.player_limit} players ·{" "}
                {joinLobbyInfo.viewer_count} / {joinLobbyInfo.viewer_limit} viewers
              </p>
            )}
            <div className="profile-actions">
              <button className="secondary-button" type="button" onClick={() => openLobbyMode("home")}>
                Cancel
              </button>
              <button className="login-button" type="submit">
                Join
              </button>
            </div>
            <p className="form-message" role="status" aria-live="polite">
              {joinMessage}
            </p>
          </form>
        </div>
      )}

      {lobbyMode === "create" && !createdInvite && (
        <div className="profile-modal" role="dialog" aria-modal="true" aria-labelledby="create-title">
          <form className="lobby-sheet" onSubmit={submitCreateLobby}>
            <p className="status-kicker">Create lobby</p>
            <h2 id="create-title">Setup race room</h2>
            <label htmlFor="lobby-name">Lobby name</label>
            <input
              id="lobby-name"
              type="text"
              autoFocus
              maxLength="32"
              value={lobbyName}
              onChange={(event) => setLobbyName(event.target.value)}
              placeholder="Friday sprint"
            />

            <div className="setup-grid">
              <div>
                <label htmlFor="player-limit">Lobby size</label>
                <input
                  id="player-limit"
                  type="number"
                  min="2"
                  max="12"
                  value={playerLimit}
                  onChange={(event) => setPlayerLimit(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="viewer-limit">Viewer size</label>
                <input
                  id="viewer-limit"
                  type="number"
                  min="0"
                  max="100"
                  value={viewerLimit}
                  onChange={(event) => setViewerLimit(event.target.value)}
                />
              </div>
            </div>

            <div className="profile-actions">
              <button className="secondary-button" type="button" onClick={() => openLobbyMode("home")}>
                Cancel
              </button>
              <button className="login-button" type="submit">
                Create
              </button>
            </div>
            <p className="form-message" role="status" aria-live="polite">
              {createMessage}
            </p>
          </form>
        </div>
      )}

      {createdInvite && (
        <div className="profile-modal" role="dialog" aria-modal="true" aria-labelledby="invite-title">
          <div className="lobby-sheet invite-sheet">
            <p className="status-kicker">Lobby ready</p>
            <h2 id="invite-title">{createdInvite.name}</h2>
            <div className="invite-code">{createdInvite.code}</div>
            <label htmlFor="invite-link">Invite link</label>
            <input id="invite-link" type="text" readOnly value={createdInvite.link} />
            <p className="invite-meta">
              {createdInvite.playerCount} / {createdInvite.players} players ·{" "}
              {createdInvite.viewerCount} / {createdInvite.viewers} viewers
            </p>
            <button className="login-button" type="button" onClick={enterCreatedGame}>
              Continue to game
            </button>
          </div>
        </div>
      )}

      {profileOpen && (
        <div className="profile-modal" role="dialog" aria-modal="true" aria-labelledby="profile-title">
          <form className="profile-sheet" onSubmit={saveName}>
            <p className="status-kicker">Profile</p>
            <h2 id="profile-title">Change in-game name</h2>
            <label htmlFor="profile-ingame-name">In-game name</label>
            <input
              id="profile-ingame-name"
              type="text"
              maxLength="18"
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
            />
            <div className="profile-actions">
              <button className="secondary-button" type="button" onClick={() => setProfileOpen(false)}>
                Cancel
              </button>
              <button className="login-button" type="submit">
                Save
              </button>
            </div>
            <p className="form-message" role="status" aria-live="polite">
              {message}
            </p>
          </form>
        </div>
      )}
    </main>
  );
}

export default Lobby;
