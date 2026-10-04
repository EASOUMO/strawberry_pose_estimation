"""
train_detection.py
------------------
Train YOLOv5s for ripe strawberry detection.

Reproduces the paper's training setup (Xie et al. 2024, Section 2.4):
  Model       : YOLOv5s
  Dataset     : 2152 fruit images  (replace with yours)
  Resolution  : 640 × 640
  Batch size  : 40
  Epochs      : 300
  Optimiser   : SGD
  LR₀         : 0.01
  Weight decay: 0.0005
  Result      : Precision 97.6 %  Recall 93.7 %  AP@0.5 98.0 %

Hardware note:
  Paper used RTX 4090 (24 GB).
  If you have less VRAM, reduce --batch (e.g. 16) and use --device 0.
  On CPU only, set --device cpu and expect ~10× slower training.

Usage:
    python train_detection.py
    python train_detection.py --batch 16 --device 0        # GPU, less VRAM
    python train_detection.py --epochs 100 --device cpu    # quick smoke test
"""

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train YOLOv5s fruit detection")
    p.add_argument("--data",    default="/home/users/esoumo/HarvestBot/src/strawberry_perception/training/configs/strawberry_detect.yaml")
    p.add_argument("--weights", default="yolov5s.pt",
                   help="Starting weights. 'yolov5s.pt' downloads COCO pretrained.")
    p.add_argument("--epochs",  type=int, default=300)
    p.add_argument("--imgsz",   type=int, default=640)
    p.add_argument("--batch",   type=int, default=40,
                   help="Paper value: 40. Reduce if GPU OOM.")
    p.add_argument("--device",  default="0",
                   help="CUDA device id ('0') or 'cpu'")
    p.add_argument("--project", default="runs/detect")
    p.add_argument("--name",    default="strawberry_yolov5s")
    p.add_argument("--patience",type=int, default=50,
                   help="Early stopping patience (0 = disabled)")
    p.add_argument("--workers", type=int, default=8)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit(
            "Install ultralytics:  pip install ultralytics\n"
            "This provides the YOLO class that supports YOLOv5 models."
        )

    # ── Load pretrained YOLOv5s ───────────────────────────────────────────
    # The 'yolov5s.pt' identifier downloads the official COCO-pretrained
    # weights from Ultralytics GitHub.  Training from COCO pretrained weights
    # converges much faster than from scratch on a small agricultural dataset.
    print(f"Loading weights: {args.weights}")
    model = YOLO(args.weights)

    # ── Train ─────────────────────────────────────────────────────────────
    # All hyperparameter values match the paper (Section 2.4 / Table 1).
    print("\n── Starting YOLOv5s detection training ──")
    print(f"   data      : {args.data}")
    print(f"   epochs    : {args.epochs}")
    print(f"   imgsz     : {args.imgsz}")
    print(f"   batch     : {args.batch}")
    print(f"   device    : {args.device}")

    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        optimizer="SGD",           # paper: "optimizer … SGD"
        lr0=0.01,                  # paper: "initial learning rates … 0.01"
        lrf=0.01,                  # final LR multiplier (cosine schedule)
        momentum=0.937,
        weight_decay=0.0005,       # paper: "weight decay rates … 0.0005"
        warmup_epochs=3,
        hsv_h=0.015,               # hue augmentation
        hsv_s=0.7,                 # saturation augmentation
        hsv_v=0.4,                 # brightness augmentation (sunny/cloudy)
        degrees=10.0,              # rotation augmentation
        translate=0.1,
        scale=0.5,
        fliplr=0.5,
        mosaic=1.0,
        mixup=0.1,
        iou=0.45,                  # NMS IoU threshold
        conf=0.25,                 # inference confidence (Table 1)
        patience=args.patience,
        workers=args.workers,
        device=args.device,
        project=args.project,
        name=args.name,
        exist_ok=False,
        pretrained=True,
        plots=True,                # save training plots
        save=True,
        save_period=-1,            # save only best + last
        val=True,
        verbose=True,
    )

    best_weights = Path(args.project) / args.name / "weights" / "best.pt"
    print(f"\n── Training complete ──")
    print(f"   Best weights : {best_weights}")
    print(f"   mAP@0.5      : {results.results_dict.get('metrics/mAP50(B)', 'N/A'):.4f}")
    print(f"\nNext: python validate.py --weights {best_weights} --task detect")
    print(f"Then: python export_tensorrt.py --weights {best_weights}")


if __name__ == "__main__":
    main()
