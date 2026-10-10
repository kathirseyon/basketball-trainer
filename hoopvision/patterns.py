"""Mines repeated plays from possession token sequences."""

from __future__ import annotations

from collections import Counter

HAND = {"L": "left", "R": "right"}


def _ngrams(seq: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(seq[i : i + n]) for i in range(len(seq) - n + 1)}


def _is_sub(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    n = len(a)
    return n < len(b) and any(b[i : i + n] == a for i in range(len(b) - n + 1))


def frequent_sequences(
    sequences: list[list[str]], min_len: int = 2, max_len: int = 5, min_support: int = 2, top: int = 5
) -> list[tuple[tuple[str, ...], int]]:
    """Contiguous move sequences that appear in at least `min_support` possessions.

    Support counts possessions, not occurrences, so one long possession can't
    inflate a pattern. Patterns fully explained by a longer pattern with the
    same support are dropped, and patterns made only of a starting spot are
    ignored because they say nothing about how the player attacks.
    """
    counts: Counter = Counter()
    for seq in sequences:
        grams: set[tuple[str, ...]] = set()
        for n in range(min_len, max_len + 1):
            grams |= _ngrams(seq, n)
        counts.update(grams)
    frequent = {
        g: c for g, c in counts.items()
        if c >= min_support and sum(not t.startswith("start:") for t in g) >= 2
    }
    maximal = [
        (g, c) for g, c in frequent.items()
        if not any(c2 >= c and _is_sub(g, g2) for g2, c2 in frequent.items())
    ]
    maximal.sort(key=lambda gc: (gc[1], len(gc[0])), reverse=True)
    return maximal[:top]


def follow_ups(sequences: list[list[str]], prefix: str) -> Counter:
    """What comes right after each token starting with `prefix` ("end" if nothing does)."""
    out: Counter = Counter()
    for seq in sequences:
        for i, tok in enumerate(seq):
            if tok.startswith(prefix):
                out[seq[i + 1] if i + 1 < len(seq) else "end"] += 1
    return out


def describe_token(tok: str) -> str:
    kind, _, arg = tok.partition(":")
    if tok.startswith("crossover>"):
        return f"crossover to the {HAND.get(tok[-1], '?')} hand"
    if kind == "start":
        return "starts in the paint" if arg == "paint" else f"starts on the {arg}"
    if kind == "dribble":
        return f"{HAND.get(arg, '?')}-hand dribble"
    if kind == "drive":
        return "drives straight at the rim" if arg == "straight" else f"drives {arg}"
    if kind == "shot":
        return f"{arg} shot" if arg in ("spot-up", "close shot") else arg
    if tok == "turnover":
        return "loses the ball"
    if tok == "end":
        return "picks up the ball"
    return tok


def describe(pattern: tuple[str, ...] | list[str]) -> str:
    return " -> ".join(describe_token(t) for t in pattern)


def short_token(tok: str) -> str:
    """Compact form for the on-screen banner, e.g. "cross L", "drive R"."""
    kind, _, arg = tok.partition(":")
    if tok.startswith("crossover>"):
        return f"cross {tok[-1]}"
    if kind == "start":
        return arg
    if kind == "dribble":
        return f"{arg}-hand"
    if kind == "drive":
        return "drive mid" if arg == "straight" else f"drive {arg[0].upper()}"
    if kind == "shot":
        return arg
    return tok


def describe_short(pattern: tuple[str, ...] | list[str]) -> str:
    return " > ".join(short_token(t) for t in pattern if not t.startswith("start:"))
