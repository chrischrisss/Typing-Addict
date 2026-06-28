DEFAULT_RACE_DURATION = 30


def calc_cps(count, elapsed_seconds):
    if elapsed_seconds <= 0:
        return 0

    return round(count / elapsed_seconds)


def is_race_finished(elapsed_seconds, duration_seconds):
    return elapsed_seconds >= duration_seconds


def rank_players(scores):
    return [row["user_id"] for row in sorted(scores, key=lambda row: row["score"], reverse=True)]
