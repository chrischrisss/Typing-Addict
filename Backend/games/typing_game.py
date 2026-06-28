import random

PROMPTS = [
    "the quick brown fox jumps over the lazy dog",
    "typing fast is fun when your fingers know the way",
    "race your friends and keep your accuracy high",
    "practice every day and your speed will climb",
    "keep calm and type on until the timer runs out",
]


def pick_prompt():
    return random.choice(PROMPTS)


def check_progress(expected, typed):
    correct = 0
    incorrect = 0

    for i, char in enumerate(typed):
        if i >= len(expected) or char != expected[i]:
            incorrect += 1
        else:
            correct += 1

    total = correct + incorrect
    accuracy = 100

    if total > 0:
        accuracy = round((correct / total) * 100)

    return {
        "correct": correct,
        "incorrect": incorrect,
        "done": typed == expected,
        "accuracy": accuracy,
    }


def calc_wpm(correct_chars, elapsed_seconds):
    if elapsed_seconds <= 0:
        return 0

    words = correct_chars / 5
    minutes = elapsed_seconds / 60
    return round(words / minutes)


def calc_score(wpm, accuracy):
    return round(wpm * (accuracy / 100))
