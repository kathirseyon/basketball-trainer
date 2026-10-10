"""Rule-based coach: turns the analyzer summary into concrete advice.

Every tip carries the evidence it was based on, and nothing is said until
there are enough samples for the tendency to mean something.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .patterns import describe, describe_short, describe_token, follow_ups, frequent_sequences
from .structures import OPPONENT, YOU

MIN_SAMPLES = 3
OTHER_DIR = {"left": "right", "right": "left"}
HAND = {"L": "left", "R": "right"}
OTHER_HAND = {"L": "right", "R": "left"}

SHOT_COUNTERS = {
    "layup": "protect the rim: cut the drive off early, stay between them and the hoop and contest vertically",
    "close shot": "body them before they get deep; keep them out of the paint",
    "pull-up": "when they drive, don't overrun them - stop when they stop and get a hand up",
    "stepback": "stay attached when their dribble stops; expect the step back and close out instead of sagging",
    "spot-up": "close out hard and early with a high hand; they like shooting without dribbling",
    "jumper": "contest every jumper; crowd them so they have to put it on the floor",
}


@dataclass
class Tip:
    priority: float
    side: str  # "defense" | "offense" | "conditioning" | "info"
    title: str
    text: str
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} ({round(100 * k / n)}%)" if n else "0/0"


def generate_tips(summary: dict) -> list[Tip]:
    players = summary.get("players", {})
    opp = players.get(OPPONENT)
    you = players.get(YOU)
    if not opp or not you:
        return []
    tips: list[Tip] = []

    # --- How the opponent attacks -------------------------------------------
    by_dir = opp["drives"]["by_direction"]
    sided = {d: by_dir.get(d, 0) for d in ("left", "right")}
    n_sided = sum(sided.values())
    if n_sided >= MIN_SAMPLES:
        fav = max(sided, key=sided.get)
        share = sided[fav] / n_sided
        if share >= 0.65:
            tips.append(Tip(
                share * n_sided, "defense", f"Force them {OTHER_DIR[fav]}",
                f"They drive {fav} most of the time. Shade half a step to their {fav} and make them go "
                f"{OTHER_DIR[fav]}, so they have to beat you with their weaker side.",
                f"drives {fav}: {_pct(sided[fav], n_sided)}",
            ))
            won = opp["drives"]["got_past_by_direction"].get(fav, 0)
            if sided[fav] >= MIN_SAMPLES and won / sided[fav] >= 0.5:
                tips.append(Tip(
                    won + 1, "defense", "Give a bigger cushion on their drive",
                    f"They get past you on {fav} drives. Start an extra half step off and drop your "
                    f"{fav}-side foot so you can slide without crossing your feet.",
                    f"beat you going {fav}: {_pct(won, sided[fav])}",
                ))

    hands = opp["dribble_hands"]
    n_hands = sum(hands.values())
    if n_hands >= 10:
        dom = max(hands, key=hands.get)
        share = hands[dom] / n_hands
        if share >= 0.7:
            tips.append(Tip(
                share * 5, "defense", f"Take away their {HAND[dom]} hand",
                f"They dribble with their {HAND[dom]} hand almost exclusively. Pressure that side of the "
                f"ball and cut off the lane so they have to use their {OTHER_HAND[dom]} hand.",
                f"{HAND[dom]}-hand dribbles: {_pct(hands[dom], n_hands)}",
            ))

    seqs = opp["sequences"]
    after_x = follow_ups(seqs, "crossover>")
    n_x = sum(after_x.values())
    if n_x >= MIN_SAMPLES:
        nxt, k = after_x.most_common(1)[0]
        if k / n_x >= 0.6:
            tips.append(Tip(
                k + 1, "defense", "Don't bite on the crossover",
                f"After a crossover they usually {describe_token(nxt)}. Stay low through the cross "
                f"and be ready for that next move instead of reaching.",
                f"crossover -> {describe_token(nxt)}: {_pct(k, n_x)}",
            ))

    by_type = opp["shots"]["by_type"]
    n_shots = opp["shots"]["attempts"]
    if n_shots >= MIN_SAMPLES and by_type:
        fav_type, (makes, att) = max(by_type.items(), key=lambda kv: kv[1][1])
        if att / n_shots >= 0.4 and att >= 2:
            tips.append(Tip(
                att / n_shots * 4 + makes, "defense", f"Their go-to is the {fav_type}",
                f"Most of their shots are {fav_type}s - {SHOT_COUNTERS.get(fav_type, 'contest it')}.",
                f"{fav_type}: {att} of {n_shots} attempts, {makes} made",
            ))

    for zone, (makes, att) in opp["shots"]["by_zone"].items():
        if att < MIN_SAMPLES:
            continue
        rate = makes / att
        if rate >= 0.5:
            tips.append(Tip(
                rate * att, "defense", f"Deny the {zone}",
                f"They're hot from the {zone}. Meet them before they get there and contest every shot from it.",
                f"{zone}: {_pct(makes, att)}",
            ))
        elif rate <= 0.25:
            tips.append(Tip(
                (1 - rate) * att * 0.6, "defense", f"Live with shots from the {zone}",
                f"They're cold from the {zone}. Sag off a little there and spend your energy taking away their drive.",
                f"{zone}: {_pct(makes, att)}",
            ))

    for pattern, support in frequent_sequences(seqs, min_support=2, top=2):
        tips.append(Tip(
            support * 1.5 + len(pattern) * 0.5, "defense", f"Their go-to play: {describe_short(pattern)}",
            f"They keep running: {describe(pattern)}. When you see the first move, jump ahead to the last one.",
            f"seen in {support} possessions",
        ))

    if opp["possessions"] >= 5 and opp["turnovers"] / opp["possessions"] >= 0.3:
        tips.append(Tip(
            4, "defense", "Pressure the ball",
            "They lose the ball a lot when pressured. Get up on them and make them dribble.",
            f"turnovers: {_pct(opp['turnovers'], opp['possessions'])} of possessions",
        ))

    # --- How you should attack them -----------------------------------------
    cushion = opp["avg_cushion_when_defending"]
    if cushion is not None and you["possessions"] >= MIN_SAMPLES:
        meters = cushion * 1.8
        if cushion > 1.1:
            tips.append(Tip(
                3, "offense", "Shoot it - they're giving you space",
                "They play off you. Rise up on the catch or after one dribble instead of driving into them.",
                f"average gap while guarding you: {meters:.1f} m",
            ))
        elif cushion < 0.6:
            tips.append(Tip(
                3, "offense", "Attack their tight defense",
                "They crowd you. Use a jab or hesitation and blow by with a quick first step.",
                f"average gap while guarding you: {meters:.1f} m",
            ))

    y_dir = you["drives"]["by_direction"]
    y_won = you["drives"]["got_past_by_direction"]
    best = None
    for d, n in y_dir.items():
        if n >= 2:
            rate = y_won.get(d, 0) / n
            if best is None or rate > best[1]:
                best = (d, rate, n)
    if best and best[1] >= 0.5:
        d, rate, n = best
        where = "at the rim" if d == "straight" else f"{d}"
        tips.append(Tip(
            rate * n, "offense", f"Keep attacking {where}",
            f"Your drives {where} beat them. Make them prove they can stop it.",
            f"you got past on {_pct(y_won.get(d, 0), n)} drives {where}",
        ))

    y_zones = [(z, m, a) for z, (m, a) in you["shots"]["by_zone"].items() if a >= MIN_SAMPLES]
    if y_zones:
        z, m, a = max(y_zones, key=lambda r: r[1] / r[2])
        if m / a >= 0.4:
            tips.append(Tip(
                m / a * a * 0.7, "offense", f"Hunt your {z} shot",
                f"You're shooting well from the {z}. Work to get back to that spot.",
                f"{z}: {_pct(m, a)}",
            ))
        z, m, a = min(y_zones, key=lambda r: r[1] / r[2])
        if m / a <= 0.25:
            tips.append(Tip(
                a * 0.5, "offense", f"Fewer shots from the {z}",
                "That spot isn't falling against this defender; look for a drive or a better shot instead.",
                f"{z}: {_pct(m, a)}",
            ))

    # --- Conditioning --------------------------------------------------------
    for who, data, side in ((OPPONENT, opp, "offense"), (YOU, you, "conditioning")):
        early, late = data["early_speed_mps"], data["late_speed_mps"]
        if early and late and late < 0.85 * early:
            if who == OPPONENT:
                tips.append(Tip(
                    3.5, side, "They're getting tired - push the pace",
                    "Their movement drops off late. Attack early in possessions and make them chase.",
                    f"opponent speed {early:.1f} -> {late:.1f} m/s",
                ))
            else:
                tips.append(Tip(
                    2, side, "Watch your legs",
                    "Your speed drops off late; conditioning work will pay off in long runs.",
                    f"your speed {early:.1f} -> {late:.1f} m/s",
                ))

    if not tips:
        tips.append(Tip(
            0, "info", "Still learning their game",
            "Keep playing - I need a few more possessions, drives and shots before calling out tendencies.",
            f"opponent possessions: {opp['possessions']}, drives: {opp['drives']['total']}, shots: {n_shots}",
        ))
    tips.sort(key=lambda t: t.priority, reverse=True)
    return tips
