"""Coach chat: talk to Claude about the game it has been watching.

Every question is sent together with a fresh snapshot of the game data
(stats, repeated plays, rule-based tips, recent commentary), so answers are
grounded in what actually happened. Without API credentials it falls back to
an offline coach that answers from the same tips.

Post-game:  python -m hoopvision.chat runs/<timestamp>/report.json
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Callable, Iterator

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are HoopVision Coach, a basketball trainer helping a player beat a specific opponent \
in 1v1. A computer-vision system has been watching their games and gives you its data with each message \
inside <game_data>. In that data "YOU" is the person you're talking to and "OPPONENT" is the player they're \
trying to beat (display names are given under "names").

How to coach:
- Ground every claim in the data and quote the numbers ("they drove right 5 of 6 times"). If the sample is \
small or a stat is missing, say so instead of guessing; you can still give general basketball advice, but \
label it as general.
- Turn tendencies into something they can do on the next possession: stance, which side to shade, when to \
close out, which move to use, what to look for first. Short drills are welcome when they ask how to improve.
- Left/right in the data are from the attacker's view facing the hoop.
- "score" is the live game score (points per player, games won, scoring rules); use it for situational \
advice such as what to do at game point or when trailing.
- The tracking is approximate (single phone camera). Treat odd numbers with healthy skepticism.
- This is a chat on a phone-sized panel: answer in a few short paragraphs or a tight list, no headings."""


def game_context(data: dict) -> str:
    return "<game_data>\n" + json.dumps(data, separators=(",", ":"), default=str) + "\n</game_data>"


# --------------------------------------------------------------------------- offline
KEYWORDS = {
    "defense": ("guard", "defend", "stop", "defense", "contain", "lock"),
    "offense": ("score", "attack", "offense", "beat", "shoot", "drive", "get past", "get by"),
    "conditioning": ("tired", "fitness", "condition", "stamina", "legs"),
}


def offline_answer(question: str, data: dict) -> str:
    q = question.lower()
    tips = data.get("tips", [])
    names = data.get("names", {})
    opp = names.get("OPPONENT", "your opponent")
    real = [t for t in tips if t["side"] != "info"]
    if any(w in q for w in ("pattern", "repeat", "go-to", "go to", "always", "habit")):
        pats = data.get("patterns", {}).get("OPPONENT", [])
        if not pats:
            return f"I haven't seen {opp} repeat a full sequence yet - give me a few more possessions."
        lines = [f"- {p['description']} ({p['possessions']} possessions)" for p in pats]
        return f"{opp}'s repeated plays so far:\n" + "\n".join(lines)
    side = next((s for s, words in KEYWORDS.items() if any(w in q for w in words)), None)
    picked = [t for t in real if t["side"] == side] if side else real
    if not picked:
        picked = real or tips
    if not picked:
        return "I don't have enough data yet - keep playing and ask me again in a minute."
    body = "\n".join(f"- {t['title']}: {t['text']} (evidence: {t['evidence']})" for t in picked[:4])
    return f"Here's what the data says:\n{body}\n\n(Offline coach - set ANTHROPIC_API_KEY for a real conversation.)"


# --------------------------------------------------------------------------- Claude
class CoachChat:
    """Multi-turn chat. `context_fn` returns the current game data dict."""

    def __init__(self, context_fn: Callable[[], dict], model: str = DEFAULT_MODEL, client=None,
                 effort: str = "low", offline: bool = False):
        self.context_fn = context_fn
        self.model = model
        self.effort = effort
        self.messages: list = []
        self._lock = threading.Lock()
        self.client = None
        if not offline:
            try:
                import anthropic

                self.client = client or anthropic.Anthropic()
            except Exception:  # SDK missing or misconfigured: stay offline
                self.client = None

    @property
    def online(self) -> bool:
        return self.client is not None

    def ask(self, question: str) -> Iterator[str]:
        """Yields the answer as it streams in."""
        data = self.context_fn()
        if not self.online:
            yield offline_answer(question, data)
            return
        with self._lock:
            # History is append-only: each turn keeps the data snapshot it was asked with.
            turn = {"role": "user", "content": f"{game_context(data)}\n\n{question}"}
            messages = self.messages + [turn]
            try:
                with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=16000,
                    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                    messages=messages,
                    output_config={"effort": self.effort},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                ) as stream:
                    for text in stream.text_stream:
                        yield text
                    final = stream.get_final_message()
            except Exception as exc:  # network / auth / rate limit: degrade gracefully
                if _is_auth_error(exc):
                    self.client = None
                    yield "(Claude isn't set up - no valid API key found. Answering offline.)\n\n"
                else:
                    yield f"(Couldn't reach Claude: {type(exc).__name__}. Answering offline.)\n\n"
                yield offline_answer(question, data)
                return
            if final.stop_reason == "refusal":
                yield "\n\n(I can't help with that one - ask me about the game.)"
                return
            self.messages = messages + [{"role": "assistant", "content": final.content}]


def _is_auth_error(exc: Exception) -> bool:
    try:
        import anthropic

        return isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError, TypeError))
    except ImportError:
        return True


class AIAnalyst:
    """Optional colour commentary: every `interval` seconds of game time, if new
    possessions finished, ask Claude for one sharp observation. Runs in a
    background thread so the video never waits on the network."""

    PROMPT = ("You're the analyst on a live 1v1 stream. Using only the game data, give ONE short observation "
              "(max 25 words) about a tendency, a matchup edge or a change in how someone is playing. "
              "Use the players' display names. No preamble.")

    def __init__(self, chat: CoachChat, on_line: Callable[[str], None], interval: float = 30.0):
        self.chat = chat
        self.on_line = on_line
        self.interval = interval
        self._last_t = None
        self._last_possessions = 0
        self._busy = False

    def maybe_run(self, t: float, possessions: int) -> None:
        if not self.chat.online or self._busy:
            return
        if self._last_t is not None and t - self._last_t < self.interval:
            return
        if possessions <= self._last_possessions:
            return
        self._last_t, self._last_possessions, self._busy = t, possessions, True
        threading.Thread(target=self._run, args=(self.chat.context_fn(),), daemon=True).start()

    def _run(self, data: dict) -> None:
        try:
            resp = self.chat.client.beta.messages.create(
                model=self.chat.model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"{game_context(data)}\n\n{self.PROMPT}"}],
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            if resp.stop_reason != "refusal":
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                if text:
                    self.on_line(text)
        except Exception:
            pass  # commentary is best-effort
        finally:
            self._busy = False


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="hoopvision.chat", description="Chat with the coach about a recorded session")
    ap.add_argument("report", help="report.json written at the end of a session")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args(argv)
    with open(args.report) as f:
        report = json.load(f)
    data = {k: report.get(k) for k in ("names", "summary", "patterns", "tips", "commentary")}
    chat = CoachChat(lambda: data, model=args.model)
    print(f"Coach ready ({'Claude' if chat.online else 'offline'}). Ask how to beat your opponent; Ctrl-D to quit.")
    while True:
        try:
            q = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            continue
        print("coach> ", end="", flush=True)
        for chunk in chat.ask(q):
            print(chunk, end="", flush=True)
        print()


if __name__ == "__main__":
    sys.exit(main())
