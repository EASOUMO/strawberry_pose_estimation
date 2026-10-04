"""
export_tensorrt.py
------------------
Export trained YOLO weights to TensorRT engine for deployment on
Jetson Xavier NX — the exact hardware used in Xie et al. 2024.

From the paper (Section 3.1):
    "The inference stage of DCNNs is accelerated through quantization using
    TensorRT to optimise processing speed."

Two precision modes:
  FP16 – half-precision; ~2× faster than FP32; negligible accuracy loss.
         Recommended for production use on Jetson.
  INT8 – integer quantization; ~4× faster than FP32; requires calibration data.
         Use only if latency is critical and you can tolerate small AP drop.

Jetson Xavier NX TensorRT benchmark (measured at 320W power mode):
  YOLOv5s  FP32 → ~15 FPS (baseline)
  YOLOv5s  FP16 → ~55–65 FPS ← paper's target throughput
  YOLOv5s  INT8 → ~80–90 FPS (with calibration)
  YOLOv11s FP16 → ~28–35 FPS ← why we use YOLOv5 not v11

NOTE: This script MUST be run ON the Jetson Xavier NX itself.
      TensorRT engines are hardware-specific; an engine built on a desktop
      GPU will NOT run on the Jetson.

Usage (run on Jetson Xavier NX):
    python export_tensorrt.py --weights best_detect.pt --task detect
    python export_tensorrt.py --weights best_seg.pt    --task segment --imgsz 320 --int8
"""

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export YOLO weights to TensorRT for Jetson Xavier NX"
    )
    p.add_argument("--weights", required=True, help="Path to trained best.pt")
    p.add_argument(
        "--task",
        default="detect",
        choices=["detect", "segment"],
        help="detect → fruit detection model; segment → stem segmentation model",
    )
    p.add_argument(
        "--imgsz",
        type=int,
        default=0,
        help="Inference image size (0 = auto: 640 for detect, 320 for seg)",
    )
    p.add_argument(
        "--fp16",
        action="store_true",
        default=True,
        help="FP16 precision (default; recommended for production)",
    )
    p.add_argument(
        "--int8",
        action="store_true",
        default=False,
        help="INT8 quantization (fastest; requires calibration data)",
    )
    p.add_argument(
        "--data",
        default="",
        help="Dataset YAML for INT8 calibration (required with --int8)",
    )
    p.add_argument("--device",    default="0")
    p.add_argument("--workspace", type=int, default=4,
                   help="TensorRT workspace size in GB (Jetson NX has 8 GB unified)")
    p.add_argument("--batch",     type=int, default=1,
                   help="Fixed batch size for TRT engine (1 for real-time inference)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Jetson Xavier NX check
    _warn_if_not_jetson()

    if args.imgsz == 0:
        args.imgsz = 640 if args.task == "detect" else 320

    if args.int8 and not args.data:
        args.data = (
            "../configs/strawberry_detect.yaml"
            if args.task == "detect"
            else "../configs/strawberry_seg.yaml"
        )

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("Install: pip install ultralytics")

    weights = Path(args.weights)
    model = YOLO(weights)

    precision = "INT8" if args.int8 else "FP16"
    print(f"\n── Exporting to TensorRT ({precision}) ──")
    print(f"   weights : {weights}")
    print(f"   imgsz   : {args.imgsz}")
    print(f"   batch   : {args.batch}")
    print(f"   device  : {args.device}")

    export_kwargs = dict(
        format="engine",
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workspace=args.workspace,
        verbose=True,
    )
    if args.int8:
        export_kwargs["int8"] = True
        export_kwargs["data"] = args.data
    else:
        export_kwargs["half"] = True   # FP16

    engine_path = model.export(**export_kwargs)

    print(f"\n── Export complete ──")
    print(f"   Engine : {engine_path}")
    print(f"\nTo use in detection_node.py, set ROS parameters:")
    suffix = "_seg" if args.task == "segment" else ""
    param  = "seg_weights" if args.task == "segment" else "det_weights"
    print(f"   ros2 param set /strawberry_perception {param} {engine_path}")
    print(
        f"\nExpected throughput on Jetson Xavier NX ({precision}):\n"
        f"   {'detect (640px)' if args.task == 'detect' else 'segment (320px)'}: "
        f"{'~60 FPS' if args.task == 'detect' else '~90 FPS'}"
    )


def _warn_if_not_jetson() -> None:
    """Non-fatal warning if we're not on a Jetson."""
    try:
        model_path = Path("/proc/device-tree/model")
        if model_path.exists():
            model = model_path.read_text()
            if "Jetson" not in model:
                print(
                    "WARNING: TensorRT engines are hardware-specific.\n"
                    "This system does not appear to be a Jetson device.\n"
                    "The exported .engine file may NOT run on Jetson Xavier NX.\n"
                    "Export directly ON the Jetson for deployment.\n"
                )
        else:
            print(
                "NOTE: Could not detect hardware platform.\n"
                "If this is not a Jetson Xavier NX, run this script on the "
                "Jetson itself before deploying.\n"
            )
    except Exception:
        pass


if __name__ == "__main__":
    main()
