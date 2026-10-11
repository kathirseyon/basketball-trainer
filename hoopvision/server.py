"""Web dashboard: live video + court, AI commentary with a clock, and a coach chat.

    python -m hoopvision --web --source 0
    open http://localhost:8000
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from .app import Session, encode_jpeg
from .chat import CoachChat
from .commentary import clock
from .report import write_report
from .structures import Box
from .video import FrameSource

WEB_DIR = Path(__file__).parent / "web"


class Runner(threading.Thread):
    """Pulls frames, runs the session, and publishes the latest JPEG."""

    def __init__(self, session: Session, source: FrameSource, out_dir: Path, realtime: bool = True,
                 save: str | None = None, hoop: Box | None = None, max_frames: int = 0):
        super().__init__(daemon=True)
        self.session = session
        self.source = source
        self.out_dir = out_dir
        self.realtime = realtime and not source.live
        self.save = save
        self.max_frames = max_frames
        self._pending_hoop = hoop
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self.jpeg: bytes = b""
        self.seq = 0
        self.done = False
        self.report_path: Path | None = None

    def request_hoop(self, box: Box) -> None:
        self._pending_hoop = box

    def stop(self) -> None:
        self._stop.set()

    def wait_frame(self, last_seq: int, timeout: float = 2.0) -> tuple[int, bytes]:
        with self._cond:
            self._cond.wait_for(lambda: self.seq != last_seq or self.done, timeout=timeout)
            return self.seq, self.jpeg

    def run(self) -> None:
        writer = None
        start = time.monotonic()
        try:
            for idx, t, frame in self.source:
                if self._stop.is_set():
                    break
                if self._pending_hoop is not None:
                    self.session.set_hoop(frame, self._pending_hoop)
                    self._pending_hoop = None
                if self.realtime:
                    delay = start + t - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                out = self.session.process(idx, t, frame)
                if self.save:
                    if writer is None:
                        Path(self.save).parent.mkdir(parents=True, exist_ok=True)
                        fps = self.source.fps if not self.source.live else 20.0
                        writer = cv2.VideoWriter(self.save, cv2.VideoWriter_fourcc(*"mp4v"), fps,
                                                 (out.shape[1], out.shape[0]))
                    writer.write(out)
                jpeg = encode_jpeg(out)
                with self._cond:
                    self.jpeg, self.seq = jpeg, self.seq + 1
                    self._cond.notify_all()
                if self.max_frames and idx + 1 >= self.max_frames:
                    break
        finally:
            self.source.release()
            if writer is not None:
                writer.release()
            self.finish()

    def finish(self) -> None:
        s = self.session
        with s.lock:
            s.analyzer.finish()
            tips = s.tips()
            self.report_path = write_report(self.out_dir, s.analyzer, tips, s.snapshot,
                                            names=s.names, commentary=[l.text for l in s.commentator.lines])
            s.commentator.say("system", f"Session over at {clock(s.commentator.elapsed)}. Report saved to "
                                        f"{self.report_path / 'report.md'}. You can keep chatting with me.")
        with self._cond:
            self.done = True
            self._cond.notify_all()


def create_app(session: Session, runner: Runner, chat: CoachChat) -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/stream.mjpg")
    def stream():
        def frames():
            seq = -1
            while True:
                seq, jpeg = runner.wait_frame(seq)
                if jpeg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                if runner.done:
                    return

        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/state")
    def state():
        since = request.args.get("since", default=0, type=int)
        data = session.state()
        data["lines"] = session.commentator.since(since)
        data["coach"] = "claude" if chat.online else "offline"
        data["done"] = runner.done
        return jsonify(data)

    @app.post("/api/chat")
    def chat_route():
        msg = (request.get_json(silent=True) or {}).get("message", "").strip()
        if not msg:
            return jsonify(error="empty message"), 400
        return Response(stream_with_context(chat.ask(msg[:2000])), mimetype="text/plain")

    @app.post("/api/hoop")
    def hoop():
        b = request.get_json(force=True)
        box = Box.from_xywh(float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"]))
        if box.w < 3 or box.h < 3:
            return jsonify(error="box too small"), 400
        runner.request_hoop(box)
        return jsonify(ok=True)

    @app.post("/api/you")
    def you():
        b = request.get_json(force=True)
        with session.lock:
            session.identity.select_you_at(float(b["x"]), float(b["y"]))
        return jsonify(ok=True)

    @app.post("/api/swap")
    def swap():
        with session.lock:
            session.identity.swap()
        return jsonify(ok=True)

    @app.post("/api/stop")
    def stop():
        runner.stop()
        return jsonify(ok=True)

    return app
