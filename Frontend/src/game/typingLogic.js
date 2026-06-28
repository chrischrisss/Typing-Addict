const PROMPTS = [
  "the quick brown fox jumps over the lazy dog",
  "typing fast is fun when your fingers know the way",
  "race your friends and keep your accuracy high",
  "practice every day and your speed will climb",
  "keep calm and type on until the timer runs out",
];

export function pickPrompt() {
  return PROMPTS[Math.floor(Math.random() * PROMPTS.length)];
}

export function checkProgress(expected, typed) {
  let correct = 0;
  let incorrect = 0;

  for (let i = 0; i < typed.length; i++) {
    if (i >= expected.length || typed[i] !== expected[i]) {
      incorrect += 1;
    } else {
      correct += 1;
    }
  }

  const total = correct + incorrect;
  let accuracy = 100;

  if (total > 0) {
    accuracy = Math.round((correct / total) * 100);
  }

  return {
    correct,
    incorrect,
    done: typed === expected,
    accuracy,
  };
}

export function calcWpm(correctChars, elapsedSeconds) {
  if (elapsedSeconds <= 0) {
    return 0;
  }

  const words = correctChars / 5;
  const minutes = elapsedSeconds / 60;
  return Math.round(words / minutes);
}

export function calcTypingScore(wpm, accuracy) {
  return Math.round(wpm * (accuracy / 100));
}
