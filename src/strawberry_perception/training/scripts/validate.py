"""
validate.py
-----------
Evaluate trained weights on the test set and print precision / recall / AP
matching the paper's Table 1 metrics.

Paper targets (Xie et al. 2024, Table 1):
  YOLOv5s (detection) : Precision 97.6 %  Recall 93.7 %  AP@0.5 98.0 %
  YOLOv5s-seg (stem)  : Precision 92.5 %  Recall 86.6 %  AP@0.5 93.4 %

Usage:
    python validate.py --weights runs/detect/strawberry_yolov5s/weights/best.pt
    python validate.py --weights runs/segment/stem_yolov5s_seg/weights/best.pt \
                       --task segment
"""

import argparse
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_CONFIGS_DIR = _SCRIPTS_DIR.parent / "configs"
_SEG_DATA    = _SCRIPTS_DIR.parent / "data" / "strawberry_seg"

SEG_DATASET_YAMLS = [
    str(_SEG_DATA / "data.yaml"),   # dataset 0: train/  (100 images)
    str(_SEG_DATA / "data1.yaml"),  # dataset 1: train1/ (63 images)
    str(_SEG_DATA / "data2.yaml"),  # dataset 2: train2/ (330 images)
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate trained YOLO weights")
    p.add_argument("--weights", required=True, help="Path to best.pt")
    p.add_argument(
        "--task",
        default="detect",
        choices=["detect", "segment"],
    )
    p.add_argument(
        "--data",
        default="",
        help="Override dataset YAML. For segment task, use 'all' to validate on "
             "all 3 datasets individually.",
    )
    p.add_argument("--imgsz",  type=int, default=0,
                   help="Override image size (0 = use training default)")
    p.add_argument("--conf",   type=float, default=0.25,
                   help="Confidence threshold (paper: 0.25 for detect, 0.01 for seg)")
    p.add_argument("--iou",    type=float, default=0.45)
    p.add_argument("--device", default="0")
    p.add_argument("--split",  default="test", choices=["train", "val", "test"])
    return p.parse_args()


def _print_metrics(metrics, task: str) -> None:
    if task == "detect":
        p   = metrics.results_dict.get("metrics/precision(B)", 0)
        r   = metrics.results_dict.get("metrics/recall(B)",    0)
        ap  = metrics.results_dict.get("metrics/mAP50(B)",     0)
        label = "YOLOv5s detection"
        paper_p, paper_r, paper_ap = 0.976, 0.937, 0.980
    else:
        p   = metrics.results_dict.get("metrics/precision(M)", 0)
        r   = metrics.results_dict.get("metrics/recall(M)",    0)
        ap  = metrics.results_dict.get("metrics/mAP50(M)",     0)
        label = "YOLOv5s-seg segmentation"
        paper_p, paper_r, paper_ap = 0.925, 0.866, 0.934

    print(f"\n  Model   : {label}")
    print(f"  ┌─────────────┬────────┬────────┐")
    print(f"  │ Metric      │  Yours │  Paper │")
    print(f"  ├─────────────┼────────┼────────┤")
    print(f"  │ Precision   │ {p*100:5.1f} % │ {paper_p*100:5.1f} % │")
    print(f"  │ Recall      │ {r*100:5.1f} % │ {paper_r*100:5.1f} % │")
    print(f"  │ AP @ 0.5    │ {ap*100:5.1f} % │ {paper_ap*100:5.1f} % │")
    print(f"  └─────────────┴────────┴────────┘")

    if ap < paper_ap - 0.05:
        print(
            "\n  TIP: AP is more than 5% below the paper benchmark.\n"
            "  Possible causes:\n"
            "    • Not enough training data (paper: 2152 / 7251 images)\n"
            "    • Missing augmentation (run augment_stems.py for stems)\n"
            "    • Fewer training epochs (paper: 300)\n"
            "    • Domain gap (collect images with YOUR RealSense D435i)"
        )


def _run_val(model, data: str, args) -> None:
    print(f"\n── Validating on: {data} ──")
    print(f"   split : {args.split}  conf : {args.conf}  imgsz : {args.imgsz}")
    metrics = model.val(
        data=data,
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        split=args.split,
        device=args.device,
        verbose=True,
        plots=True,
    )
    print("\n── Results (IoU threshold @ 0.5) ──")
    _print_metrics(metrics, args.task)


def main() -> None:
    args = parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("Install ultralytics:  pip install ultralytics")

    if args.imgsz == 0:
        args.imgsz = 640 if args.task == "detect" else 320

    if args.conf == 0.25 and args.task == "segment":
        args.conf = 0.01

    model = YOLO(args.weights)

    # Determine which dataset(s) to validate
    if args.data == "all" and args.task == "segment":
        # Validate on each of the 3 datasets individually
        for yaml_path in SEG_DATASET_YAMLS:
            _run_val(model, yaml_path, args)
    else:
        if not args.data:
            args.data = str(
                _CONFIGS_DIR / "strawberry_detect.yaml"
                if args.task == "detect"
                else _CONFIGS_DIR / "strawberry_seg.yaml"
            )
        _run_val(model, args.data, args)


if __name__ == "__main__":
    main()
