from games.common import calc_cps


def score_clicking(click_count, elapsed_seconds):
    cps = calc_cps(click_count, elapsed_seconds)
    score = round(cps * 100)
    return {"clicks": click_count, "cps": cps, "score": score}
