import { useCallback, useEffect, useRef, useState } from "react";

const TITLES = {
  typing: "Typing round",
  clicking: "Clicking round",
  spacebar: "Spacebar round",
};

const KEYBOARD_ROWS = [
  [
    ["Backquote", "`"], ["Digit1", "1"], ["Digit2", "2"], ["Digit3", "3"],
    ["Digit4", "4"], ["Digit5", "5"], ["Digit6", "6"], ["Digit7", "7"],
    ["Digit8", "8"], ["Digit9", "9"], ["Digit0", "0"], ["Minus", "-"],
    ["Equal", "="], ["Backspace", "⌫"],
  ],
  [
    ["KeyQ", "Q"], ["KeyW", "W"], ["KeyE", "E"], ["KeyR", "R"], ["KeyT", "T"],
    ["KeyY", "Y"], ["KeyU", "U"], ["KeyI", "I"], ["KeyO", "O"], ["KeyP", "P"],
    ["BracketLeft", "["], ["BracketRight", "]"], ["Backslash", "\\"],
  ],
  [
    ["KeyA", "A"], ["KeyS", "S"], ["KeyD", "D"], ["KeyF", "F"], ["KeyG", "G"],
    ["KeyH", "H"], ["KeyJ", "J"], ["KeyK", "K"], ["KeyL", "L"],
    ["Semicolon", ";"], ["Quote", "'"], ["Enter", "Enter"],
  ],
  [
    ["ShiftLeft", "Shift"], ["KeyZ", "Z"], ["KeyX", "X"], ["KeyC", "C"],
    ["KeyV", "V"], ["KeyB", "B"], ["KeyN", "N"], ["KeyM", "M"],
    ["Comma", ","], ["Period", "."], ["Slash", "/"], ["ShiftRight", "Shift"],
  ],
  [["Space", "Space"]],
];

function Keyboard({ activeKeys }) {
  return (
    <div className="live-keyboard" aria-label="Live keyboard">
      {KEYBOARD_ROWS.map((row, rowIndex) => (
        <div className="keyboard-row" key={rowIndex}>
          {row.map(([code, label]) => (
            <span
              className={`keyboard-key key-${code} ${activeKeys.has(code) ? "active" : ""}`}
              key={code}
            >
              {label}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

function SpectatorProgress({ game, liveProgress }) {
  const fallback = (game.standings || []).slice(0, 10).map((player) => ({
    ...player,
    progress: 0,
  }));
  const currentProgress = liveProgress?.round_index === game.round_index
    ? liveProgress
    : game.live_progress?.round_index === game.round_index
      ? game.live_progress
      : null;
  const players = currentProgress?.players || fallback;

  return (
    <section className="spectator-progress" aria-label="Live player progress">
      <div className="spectator-progress-heading">
        <div>
          <p className="status-kicker">Live race</p>
          <h2>Top 10 progress</h2>
        </div>
        <span>Updates live</span>
      </div>
      <div className="progress-racers" aria-live="polite">
        {players.length > 0 ? players.map((player, index) => {
          const progress = Math.max(0, Math.min(100, Number(player.progress) || 0));
          return (
            <div className="progress-racer" key={player.user_id}>
              <div className="progress-racer-meta">
                <strong><span>#{index + 1}</span> {player.name}</strong>
                <b>{Math.round(progress)}%</b>
              </div>
              <div className="money-track">
                <div className="money-lane">
                  <span
                    className="money-marker"
                    style={{ "--player-progress": `${progress}%` }}
                    aria-hidden="true"
                  >$</span>
                </div>
              </div>
            </div>
          );
        }) : (
          <p className="progress-empty">Waiting for players...</p>
        )}
      </div>
    </section>
  );
}

function GameSequence({ code, game, isViewer, liveProgress, onLeave, onProgress, user }) {
  const [typed, setTyped] = useState("");
  const [count, setCount] = useState(0);
  const [activeKeys, setActiveKeys] = useState(() => new Set());
  const [completedRounds, setCompletedRounds] = useState(() => new Set());
  const [message, setMessage] = useState("");
  const [advancing, setAdvancing] = useState(false);
  const previousRound = useRef(game.round_index);
  const previousPhase = useRef(game.phase);
  const liveInput = useRef({ typed: "", count: 0 });
  const submittedRounds = useRef(new Set());
  const progressTimeout = useRef(null);
  const queuedProgress = useRef(null);
  const lastProgressSent = useRef(0);

  const publishProgress = useCallback((progress) => {
    if (isViewer) return;

    queuedProgress.current = {
      round_index: game.round_index,
      game_type: game.game_type,
      ...progress,
    };

    const send = () => {
      progressTimeout.current = null;
      lastProgressSent.current = Date.now();
      onProgress?.(queuedProgress.current);
      queuedProgress.current = null;
    };
    const delay = Math.max(0, 100 - (Date.now() - lastProgressSent.current));

    if (delay === 0) {
      send();
    } else if (progressTimeout.current == null) {
      progressTimeout.current = window.setTimeout(send, delay);
    }
  }, [game.game_type, game.round_index, isViewer, onProgress]);

  useEffect(() => () => {
    if (progressTimeout.current != null) {
      window.clearTimeout(progressTimeout.current);
    }
  }, []);

  const submitRound = useCallback(async (roundIndex, values) => {
    if (isViewer || submittedRounds.current.has(roundIndex)) return;

    submittedRounds.current.add(roundIndex);
    setCompletedRounds((current) => new Set(current).add(roundIndex));
    const body = roundIndex === 0
      ? { round_index: roundIndex, typed: values.typed }
      : { round_index: roundIndex, count: values.count };

    try {
      const response = await fetch(`/lobbies/${code}/game/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) {
        submittedRounds.current.delete(roundIndex);
        setCompletedRounds((current) => {
          const next = new Set(current);
          next.delete(roundIndex);
          return next;
        });
        setMessage(data.message || "Score submission failed.");
      }
    } catch {
      submittedRounds.current.delete(roundIndex);
      setCompletedRounds((current) => {
        const next = new Set(current);
        next.delete(roundIndex);
        return next;
      });
      setMessage("Score submission failed. Check your connection.");
    }
  }, [code, isViewer]);

  useEffect(() => {
    const roundChanged = previousRound.current !== game.round_index;
    const roundJustEnded = previousPhase.current === "running" && game.phase === "leaderboard";

    if (roundChanged) {
      submitRound(previousRound.current, liveInput.current);
      previousRound.current = game.round_index;
      liveInput.current = { typed: "", count: 0 };
      setTyped("");
      setCount(0);
    } else if (roundJustEnded) {
      submitRound(game.round_index, liveInput.current);
    }

    previousPhase.current = game.phase;
  }, [game.phase, game.round_index, submitRound]);

  useEffect(() => {
    const typingActive = game.phase === "running" && game.game_type === "typing" && !isViewer;

    function pressKey(event) {
      setActiveKeys((current) => new Set(current).add(event.code));
      if (!typingActive || submittedRounds.current.has(game.round_index)) return;

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
        event.preventDefault();
        setMessage("Pasting is disabled. Type the passage yourself.");
        return;
      }

      if (event.key === "Backspace") {
        event.preventDefault();
        const next = liveInput.current.typed.slice(0, -1);
        liveInput.current.typed = next;
        setTyped(next);
        publishProgress({ typed: next });
        return;
      }

      if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
      event.preventDefault();
      if (liveInput.current.typed.length >= (game.prompt?.length || 0)) return;

      const next = liveInput.current.typed + event.key;
      liveInput.current.typed = next;
      setTyped(next);
      publishProgress({ typed: next });
      setMessage("");

      if (next === game.prompt) {
        submitRound(game.round_index, { ...liveInput.current, typed: next });
      }
    }

    function releaseKey(event) {
      setActiveKeys((current) => {
        const next = new Set(current);
        next.delete(event.code);
        return next;
      });
    }

    function blockPaste(event) {
      if (typingActive) {
        event.preventDefault();
        setMessage("Pasting is disabled. Type the passage yourself.");
      }
    }

    function clearKeys() {
      setActiveKeys(new Set());
    }

    window.addEventListener("keydown", pressKey);
    window.addEventListener("keyup", releaseKey);
    window.addEventListener("paste", blockPaste);
    window.addEventListener("blur", clearKeys);
    return () => {
      window.removeEventListener("keydown", pressKey);
      window.removeEventListener("keyup", releaseKey);
      window.removeEventListener("paste", blockPaste);
      window.removeEventListener("blur", clearKeys);
    };
  }, [game.phase, game.game_type, game.prompt, game.round_index, isViewer, publishProgress, submitRound]);

  useEffect(() => {
    if (game.phase !== "running" || game.game_type !== "spacebar" || isViewer) return undefined;
    function handleSpacebar(event) {
      if ((event.code === "Space" || event.key === " ") && !event.repeat) {
        event.preventDefault();
        liveInput.current.count += 1;
        setCount(liveInput.current.count);
        publishProgress({ count: liveInput.current.count });
      }
    }
    window.addEventListener("keydown", handleSpacebar);
    return () => window.removeEventListener("keydown", handleSpacebar);
  }, [game.phase, game.game_type, isViewer, publishProgress]);

  function registerClick() {
    if (game.phase !== "running" || isViewer) return;
    liveInput.current.count += 1;
    setCount(liveInput.current.count);
    publishProgress({ count: liveInput.current.count });
  }

  async function advanceRound() {
    setAdvancing(true);
    setMessage("");
    try {
      const response = await fetch(`/lobbies/${code}/next`, {
        method: "POST",
        credentials: "include",
      });
      const data = await response.json();
      if (!response.ok) {
        setMessage(data.message || "Could not start the next round.");
        return;
      }
    } catch {
      setMessage("Could not connect to the server.");
    } finally {
      setAdvancing(false);
    }
  }

  if (game.phase === "countdown") {
    return (
      <main className="game-stage transition-screen page-enter">
        <p className="eyebrow">{TITLES[game.game_type]} begins in</p>
        <div className="countdown-number" key={game.seconds_remaining}>{game.seconds_remaining}</div>
        <h1>Get ready</h1>
      </main>
    );
  }

  if (game.phase === "leaderboard") {
    const isHost = game.host_user_id === user.user_id;
    return (
      <main className="results-page round-results page-enter">
        <p className="eyebrow">Round {game.round_index + 1} complete</p>
        <h1>Leaderboard</h1>
        <div className="results-list animated-results">
          {(game.standings || []).map((standing, index) => {
            const movement = standing.previous_rank == null ? 0 : standing.previous_rank - index;
            return (
              <div
                className={`result-row ${movement > 0 ? "rank-up" : movement < 0 ? "rank-down" : ""}`}
                style={{ "--rank-offset": `${movement * 68}px`, "--row-delay": `${index * 90}ms` }}
                key={standing.user_id}
              >
                <span>#{index + 1}</span>
                <strong>{standing.name}{standing.user_id === user.user_id ? " (You)" : ""}</strong>
                <span className="round-points">+{standing.round_score}</span>
                <b>{standing.score} pts</b>
              </div>
            );
          })}
        </div>
        {isHost ? (
          <button className="login-button next-round-button" type="button" disabled={advancing} onClick={advanceRound}>
            {game.next_game_type ? `Start ${TITLES[game.next_game_type]}` : "Show final results"}
          </button>
        ) : (
          <p className="waiting-copy light">Waiting for the host to continue.</p>
        )}
        <button className="danger-button results-leave" type="button" onClick={onLeave}>Leave lobby</button>
        <p className="form-message" role="status">{message}</p>
      </main>
    );
  }

  if (game.phase === "finished") {
    return (
      <main className="results-page page-enter">
        <p className="eyebrow">Race complete</p>
        <h1>Final results</h1>
        <div className="results-list">
          {(game.standings || []).map((standing, index) => (
            <div className="result-row" key={standing.user_id}>
              <span>#{index + 1}</span>
              <strong>{standing.name}{standing.user_id === user.user_id ? " (You)" : ""}</strong>
              <b>{standing.score} pts</b>
            </div>
          ))}
        </div>
        <button className="danger-button" type="button" onClick={onLeave}>Leave lobby</button>
      </main>
    );
  }

  const typingComplete = completedRounds.has(game.round_index);

  return (
    <main className={`game-stage page-enter${isViewer ? " spectator-stage" : ""}`}>
      <header className="game-header">
        <div>
          <p className="eyebrow">Round {game.round_index + 1} of {game.game_order?.length || 3}</p>
          <h1>{TITLES[game.game_type]}</h1>
        </div>
        <div className="game-timer">{game.seconds_remaining}</div>
        <button className="danger-button" type="button" onClick={onLeave}>Leave</button>
      </header>

      {isViewer && <p className="spectator-banner">Spectating — player progress updates live.</p>}

      {isViewer && <SpectatorProgress game={game} liveProgress={liveProgress} />}

      {!isViewer && game.game_type === "typing" && (
        <section className="typing-board integrated-typing" aria-label="Typing passage">
          <div className="typing-overlay" aria-live="polite">
            {game.prompt?.split("").map((character, index) => {
              const entered = typed[index];
              const state = entered == null ? "pending" : entered === character ? "correct" : "incorrect";
              const caret = index === typed.length && !typingComplete ? " caret" : "";
              return (
                <span className={`typed-character ${state}${caret}`} key={index}>
                  {character}
                </span>
              );
            })}
          </div>
          <p className={`typing-status ${typingComplete ? "complete" : ""}`}>
            {isViewer
              ? "Watching the typing round"
              : typingComplete
                ? "Passage complete — score submitted."
                : "Type the passage. Backspace corrects mistakes; paste is disabled."}
          </p>
          <Keyboard activeKeys={activeKeys} />
        </section>
      )}

      {!isViewer && game.game_type === "clicking" && (
        <section className="action-board">
          <div className="action-count">{count}</div>
          <button className="click-target" type="button" disabled={isViewer} onClick={registerClick}>
            {isViewer ? "Spectating" : "Click me"}
          </button>
        </section>
      )}

      {!isViewer && game.game_type === "spacebar" && (
        <section className="action-board">
          <div className="action-count">{count}</div>
          <div className={`spacebar-key ${activeKeys.has("Space") ? "active" : ""}`}>Spacebar</div>
          <p>{isViewer ? "Spectating" : "Press the spacebar as fast as possible"}</p>
        </section>
      )}
      <p className="form-message" role="status">{message}</p>
    </main>
  );
}

export default GameSequence;
