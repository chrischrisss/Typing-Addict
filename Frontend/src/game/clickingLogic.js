import { calcCps } from "./common.js";

export function scoreClicking(clickCount, elapsedSeconds) {
  const cps = calcCps(clickCount, elapsedSeconds);
  const score = Math.round(cps * 100);
  return { clicks: clickCount, cps, score };
}
