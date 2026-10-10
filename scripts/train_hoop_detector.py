"""Fine-tune a small YOLO model to detect the hoop (and ball).

Stock COCO models have no "hoop" class. To get automatic hoop detection:

1. Grab a labelled basketball dataset in YOLO format (Roboflow Universe has
   several "basketball hoop" / "basketball and hoop" datasets), or label ~200
   frames of your own court footage.
2. Run:  python scripts/train_hoop_detector.py --data path/to/data.yaml
3. Use:  python -m hoopvision --hoop-weights runs/detect/hoop/weights/best.pt

Any class whose name contains "hoop", "rim", "basket" or "net" is used as the
hoop, and any class containing "ball" replaces COCO's ball detector when it is
more confident.
"""

import argparse

from ultralytics import YOLO


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="YOLO dataset yaml")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None)
    args = ap.parse_args()
    YOLO(args.model).train(data=args.data, epochs=args.epochs, imgsz=args.imgsz, device=args.device, name="hoop")


if __name__ == "__main__":
    main()
