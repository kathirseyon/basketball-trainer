"""Command line entry point: ``python -m hoopvision --source 0``."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

from .analyzer import AnalyzerConfig, GameAnalyzer
from .app import Session
from .hoop import HoopTracker
from .identity import IdentityAssigner
from .report import write_report
from .structures import Box
from .video import FrameSource

WINDOW = "HoopVision"
KEYS_HELP = "keys: q quit | space pause | s swap YOU/OPPONENT | click a player to mark YOU | h reselect hoop"


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="hoopvision", description="1v1 basketball tracker and scouting coach")
    ap.add_argument("--source", default="0",
                    help="webcam index (0), video file, or phone stream URL, e.g. http://192.168.1.20:8080/video")
    ap.add_argument("--save", help="write the annotated video to this .mp4")
    ap.add_argument("--report-dir", help="where to write the scouting report (default runs/<timestamp>)")
    ap.add_argument("--no-display", action="store_true", help="run headless (no window)")
    ap.add_argument("--width", type=int, default=1280, help="resize frames to this width (0 = keep)")
    ap.add_argument("--you-side", choices=["left", "right"], default="left",
                    help="which side of the frame YOU start on (or click yourself in the window)")
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
    ap.add_argument("--max-frames", type=int, default=0)
    return ap.parse_args(argv)


def _select_hoop(frame) -> Box | None:
    r = cv2.selectROI("Drag a box around the HOOP (rim + net), then press ENTER", frame, showCrosshair=False)
    cv2.destroyWindow("Drag a box around the HOOP (rim + net), then press ENTER")
    x, y, w, h = map(int, r)
    return Box.from_xywh(x, y, w, h) if w > 2 and h > 2 else None


def main(argv=None) -> int:
    args = parse_args(argv)
    from .detection import YoloDetector  # heavy import after arg parsing

    display = not args.no_display
    detector = YoloDetector(
        pose_weights=args.pose_weights,
        ball_weights=None if args.ball_weights.lower() == "none" else args.ball_weights,
        hoop_weights=args.hoop_weights,
        device=args.device,
        imgsz=args.imgsz,
    )
    session = Session(
        detector,
        identity=IdentityAssigner(you_side=args.you_side),
        analyzer=GameAnalyzer(AnalyzerConfig(mirror=args.camera_behind_hoop)),
        hoop=HoopTracker(),
        show_skeleton=args.skeleton,
    )

    source = FrameSource(args.source, width=args.width or None)
    out_dir = Path(args.report_dir or f"runs/{time.strftime('%Y%m%d-%H%M%S')}")
    writer = None
    paused = False
    hoop_mode = args.hoop or ("select" if display and not args.hoop_weights else None)
    if hoop_mode is None and not args.hoop_weights:
        print("No hoop location given: shot results and drive directions need one. Use --hoop x,y,w,h.",
              file=sys.stderr)

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
                    session.hoop.set_manual(frame, box)

            annotated = session.process(idx, t, frame)

            if args.save:
                if writer is None:
                    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
                    fps = source.fps if not source.live else 20.0
                    h, w = annotated.shape[:2]
                    writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                writer.write(annotated)

            if not display and idx % 100 == 0:
                total = f"/{source.frame_count}" if source.frame_count else ""
                print(f"frame {idx}{total}", file=sys.stderr)

            if display:
                cv2.imshow(WINDOW, annotated)
                key = cv2.waitKey(0 if paused else 1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord(" "):
                    paused = not paused
                elif key == ord("s"):
                    session.identity.swap()
                elif key == ord("h"):
                    box = _select_hoop(frame)
                    if box is not None:
                        session.hoop.set_manual(frame, box)
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
    path = write_report(out_dir, session.analyzer, tips, session.snapshot)
    print("\n=== Coaching tips ===")
    for tip in tips:
        print(f"[{tip.side}] {tip.title}: {tip.text}\n    evidence: {tip.evidence}")
    print(f"\nFull report: {path / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
