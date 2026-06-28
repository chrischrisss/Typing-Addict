import { calcCps } from "./common.js";

export function scoreSpacebar(pressCount, elapsedSeconds) {
  const cps = calcCps(pressCount, elapsedSeconds);
  const score = Math.round(cps * 100);
  return { presses: pressCount, cps, score };
}

export function isSpacebarKey(event) {
  return event.code === "Space" || event.key === " ";
}
