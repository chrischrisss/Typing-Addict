import { useMemo, useState } from "react";

// Edit this list to control which in-game names are blocked.
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

const CODE_CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function generateLobbyCode() {
  while (true) {
    const code = Array.from({ length: 6 }, () =>
      CODE_CHARACTERS[Math.floor(Math.random() * CODE_CHARACTERS.length)]
    ).join("");

    if (/[A-Z]/.test(code) && /[0-9]/.test(code)) {
      return code;
    }
  }
}

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

function Lobby({ handleLogout, user }) {
  const storageKey = `typing-addict-ingame-name-${user.user_id}`;
  const [savedName, setSavedName] = useState(() => localStorage.getItem(storageKey) || "");
  const [draftName, setDraftName] = useState(savedName);
  const [profileOpen, setProfileOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [lobbyMode, setLobbyMode] = useState("home");
  const [joinCode, setJoinCode] = useState("");
  const [joinMessage, setJoinMessage] = useState("");
  const [lobbyName, setLobbyName] = useState("");
  const [playerLimit, setPlayerLimit] = useState(4);
  const [viewerLimit, setViewerLimit] = useState(12);
  const [createMessage, setCreateMessage] = useState("");
  const [createdInvite, setCreatedInvite] = useState(null);
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

  function saveName(event) {
    event.preventDefault();
    const validationMessage = validateInGameName(draftName);

    if (validationMessage) {
      setMessage(validationMessage);
      return;
    }

    const cleanName = draftName.trim().replace(/\s+/g, " ");
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
  }

  function submitJoinLobby(event) {
    event.preventDefault();
    const cleanCode = joinCode.trim().toUpperCase();

    if (!/^[A-Z0-9]{6}$/.test(cleanCode) || !/[A-Z]/.test(cleanCode) || !/[0-9]/.test(cleanCode)) {
      setJoinMessage("Enter a 6-character lobby code using letters and numbers.");
      return;
    }

    setActiveGame({
      code: cleanCode,
      name: "Joined lobby",
      role: "player",
    });
  }

  function submitCreateLobby(event) {
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

    const code = generateLobbyCode();
    const link = `${window.location.origin}/?lobby=${code}`;

    setCreatedInvite({
      code,
      link,
      name: cleanLobbyName,
      players,
      viewers,
    });
    setCreateMessage("");
  }

  function enterCreatedGame() {
    setActiveGame({
      code: createdInvite.code,
      name: createdInvite.name,
      role: "host",
    });
  }

  if (activeGame) {
    return <main className="game-page" aria-label="Typing game placeholder" />;
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
              onChange={(event) => setJoinCode(event.target.value.toUpperCase())}
              placeholder="A1B2C3"
            />
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
              {createdInvite.players} players / {createdInvite.viewers} viewers
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
