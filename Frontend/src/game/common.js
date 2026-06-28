export const DEFAULT_RACE_DURATION = 30;

export function calcCps(count, elapsedSeconds) {
  if (elapsedSeconds <= 0) {
    return 0;
  }

  return Math.round(count / elapsedSeconds);
}

export function isRaceFinished(elapsedSeconds, durationSeconds) {
  return elapsedSeconds >= durationSeconds;
}

export function rankPlayers(scores) {
  return [...scores].sort((a, b) => b.score - a.score).map((score) => score.user_id);
}
