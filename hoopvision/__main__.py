"""Command line entry point.

    python -m hoopvision --web --source 0          # dashboard with commentary + coach chat
    python -m hoopvision --source game.mp4         # OpenCV window
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from pathlib import Path

import cv2

from .analyzer import AnalyzerConfig, GameAnalyzer
from .app import Session
from .chat import DEFAULT_MODEL, CoachChat
from .hoop import HoopTracker
from .identity import IdentityAssigner
from .report import write_report
from .scoring import SCORING_SYSTEMS, Scoreboard
from .structures import OPPONENT, YOU, Box
from .video import FrameSource

WINDOW = "HoopVision"
KEYS_HELP = ("keys: q quit | space pause | s swap players | click a player to mark YOU | h reselect hoop\n"
             "      1 / 2 add a point to YOU / OPPONENT | u undo last score change")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="hoopvision", description="1v1 basketball tracker, commentator and coach")
    ap.add_argument("--source", default="0",
                    help="webcam index (0), video file, or phone stream URL, e.g. http://192.168.1.20:8080/video")
    ap.add_argument("--web", action="store_true", help="run the web dashboard (commentary + coach chat)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--you-name", default=YOU, help="label for you")
    ap.add_argument("--opp-name", default=OPPONENT, help="label for your opponent, e.g. WEMBY")
    ap.add_argument("--scoring", choices=sorted(SCORING_SYSTEMS), default="1s2s",
                    help="1s2s: 1 inside the arc, 2 behind it (streetball); 2s3s: regular 2s and 3s")
    ap.add_argument("--game-to", type=int, default=11, help="points needed to win a game")
    ap.add_argument("--win-by", type=int, default=1, help="winning margin required (2 = win by two)")
    ap.add_argument("--save", help="write the annotated video to this .mp4")
    ap.add_argument("--report-dir", help="where to write the scouting report (default runs/<timestamp>)")
    ap.add_argument("--no-display", action="store_true", help="run headless (no window)")
    ap.add_argument("--no-court", action="store_true", help="hide the LIVE COURT minimap")
    ap.add_argument("--no-ai", action="store_true", help="never call Claude (offline coach only)")
    ap.add_argument("--no-ai-commentary", action="store_true", help="chat with Claude but skip AI commentary lines")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Claude model for the coach")
    ap.add_argument("--scout-possessions", type=int, default=5,
                    help="opponent possessions to watch before the game plan is 'ready'")
    ap.add_argument("--width", type=int, default=1280, help="resize frames to this width (0 = keep)")
    ap.add_argument("--you-side", choices=["left", "right"], default="left",
                    help="which side of the frame YOU start on (or click yourself)")
    ap.add_argument("--hoop", default=None,
                    help="'select' to drag a box around the hoop, or x,y,w,h in pixels of the resized frame")
    ap.add_argument("--camera-behind-hoop", action="store_true",
                    help="phone is behind the hoop facing the players (flips left/right)")
    ap.add_argument("--pose-weights", default="yolo11n-pose.pt")
    ap.add_argument("--ball-weights", default="yolo11n.pt", help="'none' to disable COCO ball detection")
    ap.add_argument("--hoop-weights", help="custom YOLO model with a hoop/rim class (and optionally ball)")
    ap.add_argument("--device", help="cpu, mps, 0 (CUDA) ...")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--skeleton", action="store_true", help="draw pose skeletons")
    ap.add_argument("--no-realtime", action="store_true", help="web mode: process video files as fast as possible")
    ap.add_argument("--max-frames", type=int, default=0)
    return ap.parse_args(argv)


def _select_hoop(frame) -> Box | None:
    title = "Drag a box around the HOOP (rim + net), then press ENTER"
    r = cv2.selectROI(title, frame, showCrosshair=False)
    cv2.destroyWindow(title)
    x, y, w, h = map(int, r)
    return Box.from_xywh(x, y, w, h) if w > 2 and h > 2 else None


def build_session(args) -> Session:
    from .detection import YoloDetector  # heavy import after arg parsing

    detector = YoloDetector(
        pose_weights=args.pose_weights,
        ball_weights=None if args.ball_weights.lower() == "none" else args.ball_weights,
        hoop_weights=args.hoop_weights,
        device=args.device,
        imgsz=args.imgsz,
    )
    return Session(
        detector,
        identity=IdentityAssigner(you_side=args.you_side),
        analyzer=GameAnalyzer(AnalyzerConfig(mirror=args.camera_behind_hoop)),
        hoop=HoopTracker(),
        names={YOU: args.you_name.upper(), OPPONENT: args.opp_name.upper()},
        show_skeleton=args.skeleton,
        show_court=not args.no_court,
        scout_target=args.scout_possessions,
        can_detect_hoop=bool(args.hoop_weights),
        scoreboard=Scoreboard(scoring=args.scoring, game_to=args.game_to, win_by=args.win_by),
    )


def run_web(args, session: Session, source: FrameSource, out_dir: Path) -> int:
    from .server import Runner, create_app

    chat = CoachChat(session.context, model=args.model, offline=args.no_ai)
    session.enable_ai(chat, commentary=not args.no_ai_commentary)
    hoop = None
    if args.hoop and args.hoop != "select":
        hoop = Box.from_xywh(*map(float, args.hoop.split(",")))
    runner = Runner(session, source, out_dir, realtime=not args.no_realtime, save=args.save, hoop=hoop,
                    max_frames=args.max_frames)
    runner.start()
    app = create_app(session, runner, chat)
    url = f"http://localhost:{args.port}"
    print(f"HoopVision dashboard: {url}  (coach: {'Claude' if chat.online else 'offline'})")
    if not args.no_display:
        webbrowser.open(url)
    app.run(host="0.0.0.0", port=args.port, threaded=True)
    return 0


def run_window(args, session: Session, source: FrameSource, out_dir: Path) -> int:
    display = not args.no_display
    writer = None
    paused = False
    hoop_mode = args.hoop or ("select" if display and not args.hoop_weights else None)
    printed = 0

    if display:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(
            WINDOW, lambda ev, x, y, *_: ev == cv2.EVENT_LBUTTONDOWN and session.identity.select_you_at(x, y))
        print(KEYS_HELP)

    try:
        for idx, t, frame in source:
            if idx == 0 and hoop_mode:
                box = None
                if hoop_mode == "select" and display:
                    box = _select_hoop(frame)
                elif hoop_mode != "select":
                    box = Box.from_xywh(*map(float, hoop_mode.split(",")))
                if box is not None:
                    session.set_hoop(frame, box)

            annotated = session.process(idx, t, frame)
            for line in session.commentator.lines[printed:]:
                print(f"[{line.clock}] {line.text}")
            printed = len(session.commentator.lines)

            if args.save:
                if writer is None:
                    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
                    fps = source.fps if not source.live else 20.0
                    h, w = annotated.shape[:2]
                    writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                writer.write(annotated)

            if display:
                cv2.imshow(WINDOW, annotated)
                key = cv2.waitKey(0 if paused else 1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord(" "):
                    paused = not paused
                elif key == ord("s"):
                    session.identity.swap()
                elif key == ord("1"):
                    session.adjust_score(YOU, 1)
                elif key == ord("2"):
                    session.adjust_score(OPPONENT, 1)
                elif key == ord("u"):
                    session.undo_score()
                elif key == ord("h"):
                    box = _select_hoop(frame)
                    if box is not None:
                        session.set_hoop(frame, box)
            if args.max_frames and idx + 1 >= args.max_frames:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.release()
        if writer is not None:
            writer.release()
        if display:
            cv2.destroyAllWindows()

    session.analyzer.finish()
    tips = session.tips()
    path = write_report(out_dir, session.analyzer, tips, session.snapshot, names=session.names,
                        commentary=[l.text for l in session.commentator.lines],
                        score=session.scoreboard.to_dict())
    print(f"\nScore: {session.score_text()}  (games won: "
          f"{session.names[YOU]} {session.scoreboard.games_won[YOU]} - "
          f"{session.names[OPPONENT]} {session.scoreboard.games_won[OPPONENT]})")
    print("\n=== Coaching tips ===")
    for tip in tips:
        print(f"[{tip.side}] {tip.title}: {tip.text}\n    evidence: {tip.evidence}")
    print(f"\nFull report: {path / 'report.md'}")
    print(f"Chat with the coach about it: python -m hoopvision.chat {path / 'report.json'}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    session = build_session(args)
    source = FrameSource(args.source, width=args.width or None)
    out_dir = Path(args.report_dir or f"runs/{time.strftime('%Y%m%d-%H%M%S')}")
    if args.web:
        return run_web(args, session, source, out_dir)
    return run_window(args, session, source, out_dir)


if __name__ == "__main__":
    sys.exit(main())
