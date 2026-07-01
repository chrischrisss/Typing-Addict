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
  const [joinMessage, setJoinMessage] = useState("");
  const [inviteNotice, setInviteNotice] = useState("");
  const [lobbyName, setLobbyName] = useState("");
  const [lobbyLimit, setLobbyLimit] = useState(16);
  const [playerLimit, setPlayerLimit] = useState(4);
  const [bidderLimit, setBidderLimit] = useState(12);
  const [typingRounds, setTypingRounds] = useState(1);
  const [clickingRounds, setClickingRounds] = useState(1);
  const [spacebarRounds, setSpacebarRounds] = useState(1);
  const [roundDuration, setRoundDuration] = useState(30);
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
        setJoinMessage(`${data.name} is open. Player spots are filled first.`);
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
          bidderCount: data.bidder_count,
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

  async function syncInGameName() {
    if (!savedName || savedName === user.display_name) {
      return true;
    }

    const response = await fetch("/me/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ display_name: savedName }),
    });
    return response.ok;
  }

  async function submitJoinLobby(event) {
    event.preventDefault();
    const cleanCode = joinCode.trim().toUpperCase();

    if (!/^[A-Z0-9]{6}$/.test(cleanCode) || !/[A-Z]/.test(cleanCode) || !/[0-9]/.test(cleanCode)) {
      setJoinMessage("Enter a 6-character lobby code using letters and numbers.");
      return;
    }

    setJoinMessage("");

    try {
      if (!await syncInGameName()) {
        setJoinMessage("Could not save your in-game name.");
        return;
      }
      const response = await fetch(`/lobbies/${cleanCode}/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({}),
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
    const lobbySize = Number(lobbyLimit);
    const players = Number(playerLimit);
    const bidders = Number(bidderLimit);
    const modeRounds = [typingRounds, clickingRounds, spacebarRounds].map(Number);
    const seconds = Number(roundDuration);

    if (cleanLobbyName.length < 3 || cleanLobbyName.length > 32) {
      setCreateMessage("Lobby name must be 3 to 32 characters.");
      return;
    }

    if (!Number.isInteger(lobbySize) || lobbySize < 1 || lobbySize > 100) {
      setCreateMessage("Lobby size must be between 1 and 100.");
      return;
    }

    if (!Number.isInteger(players) || players < 1 || players > 100) {
      setCreateMessage("Player size must be between 1 and 100.");
      return;
    }

    if (!Number.isInteger(bidders) || bidders < 0 || bidders > 50) {
      setCreateMessage("Bidder size must be between 0 and 50.");
      return;
    }

    if (modeRounds.some((rounds) => !Number.isInteger(rounds) || rounds < 1 || rounds > 10)) {
      setCreateMessage("Each game mode must have 1 to 10 rounds.");
      return;
    }

    if (!Number.isInteger(seconds) || seconds < 5 || seconds > 300) {
      setCreateMessage("Round time must be between 5 and 300 seconds.");
      return;
    }

    setCreateMessage("");

    try {
      if (!await syncInGameName()) {
        setCreateMessage("Could not save your in-game name.");
        return;
      }
      const response = await fetch("/lobbies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: cleanLobbyName,
          lobby_limit: lobbySize,
          player_limit: players,
          bidder_limit: bidders,
          typing_rounds: modeRounds[0],
          clicking_rounds: modeRounds[1],
          spacebar_rounds: modeRounds[2],
          round_duration: seconds,
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
        lobbySize: data.lobby_limit,
        players: data.player_limit,
        bidders: data.bidder_limit,
        playerCount: data.player_count,
        bidderCount: data.bidder_count,
        typingRounds: data.typing_rounds,
        clickingRounds: data.clicking_rounds,
        spacebarRounds: data.spacebar_rounds,
        roundDuration: data.round_duration,
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
      lobby_limit: createdInvite.lobbySize,
      player_limit: createdInvite.players,
      bidder_limit: createdInvite.bidders,
      players: [],
      bidders: [],
      typing_rounds: createdInvite.typingRounds,
      clicking_rounds: createdInvite.clickingRounds,
      spacebar_rounds: createdInvite.spacebarRounds,
      round_duration: createdInvite.roundDuration,
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
            <p className="random-role-note">
              Player spots are filled first. Once full, new arrivals join as bidders.
            </p>
            {joinLobbyInfo && (
              <p className="invite-meta">
                {joinLobbyInfo.player_count + joinLobbyInfo.bidder_count} / {joinLobbyInfo.lobby_limit} total ·{" "}
                {joinLobbyInfo.player_count} / {joinLobbyInfo.player_limit} players ·{" "}
                {joinLobbyInfo.bidder_count} / {joinLobbyInfo.bidder_limit} bidders
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
                <label htmlFor="lobby-limit">Lobby size</label>
                <input
                  id="lobby-limit"
                  type="number"
                  min="1"
                  max="100"
                  value={lobbyLimit}
                  onChange={(event) => setLobbyLimit(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="player-limit">Player size</label>
                <input
                  id="player-limit"
                  type="number"
                  min="1"
                  max="100"
                  value={playerLimit}
                  onChange={(event) => setPlayerLimit(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="bidder-limit">Bidder size</label>
                <input
                  id="bidder-limit"
                  type="number"
                  min="0"
                  max="50"
                  value={bidderLimit}
                  onChange={(event) => setBidderLimit(event.target.value)}
                />
              </div>
            </div>

            <p className="settings-heading">Rounds per game mode</p>
            <div className="setup-grid rounds-grid">
              <div>
                <label htmlFor="typing-rounds">Typing</label>
                <input
                  id="typing-rounds"
                  type="number"
                  min="1"
                  max="10"
                  value={typingRounds}
                  onChange={(event) => setTypingRounds(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="clicking-rounds">Clicking</label>
                <input
                  id="clicking-rounds"
                  type="number"
                  min="1"
                  max="10"
                  value={clickingRounds}
                  onChange={(event) => setClickingRounds(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="spacebar-rounds">Spacebar</label>
                <input
                  id="spacebar-rounds"
                  type="number"
                  min="1"
                  max="10"
                  value={spacebarRounds}
                  onChange={(event) => setSpacebarRounds(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="round-duration">Seconds each</label>
                <input
                  id="round-duration"
                  type="number"
                  min="5"
                  max="300"
                  value={roundDuration}
                  onChange={(event) => setRoundDuration(event.target.value)}
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
              {createdInvite.playerCount + createdInvite.bidderCount} / {createdInvite.lobbySize} total ·{" "}
              {createdInvite.playerCount} / {createdInvite.players} players ·{" "}
              {createdInvite.bidderCount} / {createdInvite.bidders} bidders
            </p>
            <p className="invite-settings">
              {createdInvite.typingRounds} typing · {createdInvite.clickingRounds} clicking ·{" "}
              {createdInvite.spacebarRounds} spacebar · {createdInvite.roundDuration}s each
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
