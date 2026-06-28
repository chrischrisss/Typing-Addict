from games.common import calc_cps


def score_spacebar(press_count, elapsed_seconds):
    cps = calc_cps(press_count, elapsed_seconds)
    score = round(cps * 100)
    return {"presses": press_count, "cps": cps, "score": score}
