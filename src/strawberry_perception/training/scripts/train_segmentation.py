"""
train_segmentation.py
---------------------
Train YOLOv5s-seg for strawberry stem instance segmentation.

Paper setup (Xie et al. 2024, Section 2.4):
  Model       : YOLOv5s-seg
  Dataset     : 7251 stem images  (after augmentation)
  Resolution  : 320 × 320          ← smaller than detection (stems are thin)
  Batch size  : 60
  Epochs      : 300
  Optimiser   : SGD
  LR₀         : 0.01
  Weight decay: 0.0005
  Result      : Precision 92.5 %  Recall 86.6 %  AP@0.5 93.4 %

IMPORTANT – run augment_stems.py BEFORE this script:
    python augment_stems.py --split train --multiplier 3
    # This triples the training set using rotation, brightness, motion blur.

Annotation format (YOLO-SEG polygon):
    <class> <x1> <y1> <x2> <y2> ... <xn> <yn>
    All coordinates normalised to [0, 1].
    Use Labelme with polygon tool → export to YOLO format.

Usage:
    python train_segmentation.py
    python train_segmentation.py --batch 30 --device 0   # less VRAM
"""

import argparse
from pathlib import Path

# Resolve paths relative to this script file, not the caller's CWD
_SCRIPTS_DIR = Path(__file__).resolve().parent
_CONFIGS_DIR = _SCRIPTS_DIR.parent / "configs"
_DATA_DIR    = _SCRIPTS_DIR.parent / "data"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train YOLOv5s-seg stem segmentation")
    p.add_argument("--data",    default=str(_CONFIGS_DIR / "strawberry_seg.yaml"))
    p.add_argument("--weights", default="yolov8s-seg.yaml",
                   help="Starting weights or architecture YAML. "
                        "yolov8s-seg.yaml (built-in) is the default; pass "
                        "yolov5s-seg.pt if you have the file locally.")
    p.add_argument("--epochs",  type=int, default=500)
    p.add_argument("--imgsz",   type=int, default=320,
                   help="Paper value: 320. Stem images are small, 320 is sufficient.")
    p.add_argument("--batch",   type=int, default=60,
                   help="Paper value: 60. Reduce if GPU OOM.")
    p.add_argument("--device",  default="0")
    p.add_argument("--project", default=str(_SCRIPTS_DIR / "runs" / "segment"))
    p.add_argument("--name",    default="stem_yolov5s_seg")
    p.add_argument("--patience",type=int, default=50)
    p.add_argument("--workers", type=int, default=8)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("Install ultralytics:  pip install ultralytics")

    # ── Validate augmentation was done (check all 3 train splits) ────────
    total_images = 0
    for split in ("train", "train1", "train2"):
        d = _DATA_DIR / "strawberry_seg" / split / "images"
        if d.exists():
            total_images += len(list(d.glob("*.[jp][pn]g")))
    if total_images > 0 and total_images < 500:
        print(
            f"WARNING: Only {total_images} training images across all 3 datasets.\n"
            "The paper used 7251. Run augment_stems.py first:\n"
            "  python augment_stems.py --split all --multiplier 3\n"
        )

    # ── Resolve weights ───────────────────────────────────────────────────
    # .yaml  → build architecture from Ultralytics built-in (no download)
    # .pt    → load checkpoint; try downloading if not present locally
    if args.weights.endswith(".pt") and not Path(args.weights).exists():
        try:
            from ultralytics.utils.downloads import attempt_download_asset
            print(f"Downloading {args.weights} ...")
            downloaded = attempt_download_asset(args.weights)
            if not Path(downloaded).exists():
                raise FileNotFoundError(downloaded)
        except Exception as exc:
            fallback = "yolov8s-seg.yaml"
            print(f"Could not download {args.weights} ({exc}).")
            print(f"Falling back to built-in architecture: {fallback}")
            args.weights = fallback

    print(f"Loading weights: {args.weights}")
    model = YOLO(args.weights)

    # ── Train ─────────────────────────────────────────────────────────────
    print("\n── Starting YOLOv5s-seg stem segmentation training ──")
    print(f"   data   : {args.data}")
    print(f"   epochs : {args.epochs}")
    print(f"   imgsz  : {args.imgsz}  (paper: 320)")
    print(f"   batch  : {args.batch}  (paper: 60)")
    print(f"   device : {args.device}")

    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        task="segment",            # instance segmentation mode
        optimizer="SGD",
        lr0=0.01,
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=3,
        # ── Augmentation (paper Figure 6) ─────────────────────────────
        # Offline augmentation (augment_stems.py) already applied:
        #   rotation, brightness, motion blur.
        # Here we add light online augmentation on top.
        hsv_h=0.010,
        hsv_s=0.5,
        hsv_v=0.5,                 # brightness variation (cloudy/sunny/rainy)
        degrees=30.0,              # heavy rotation – stem tilt is the key feature
        translate=0.1,
        scale=0.6,                 # camera distance 10–40 cm → scale variation
        shear=5.0,
        perspective=0.0002,
        fliplr=0.5,
        mosaic=0.0,            # disabled: mosaic + tiny stems can produce empty rasterized masks
        copy_paste=0.0,        # disabled: crashes on images with no masks
        overlap_mask=False,    # avoids IndexError in sem_masks when instances are filtered out
        iou=0.45,
        conf=0.01,                 # low threshold – stems are thin, low confidence
        patience=args.patience,
        workers=args.workers,
        device=args.device,
        project=args.project,
        name=args.name,
        exist_ok=False,
        pretrained=True,
        plots=True,
        save=True,
        save_period=-1,
        val=True,
        verbose=True,
    )

    best_weights = Path(args.project) / args.name / "weights" / "best.pt"
    print(f"\n── Training complete ──")
    print(f"   Best weights : {best_weights}")
    print(f"   mAP@0.5(M)   : {results.results_dict.get('metrics/mAP50(M)', 'N/A'):.4f}")
    print(f"\nNext: python validate.py --weights {best_weights} --task segment")
    print(f"Then: python export_tensorrt.py --weights {best_weights} --imgsz 320")


if __name__ == "__main__":
    main()
