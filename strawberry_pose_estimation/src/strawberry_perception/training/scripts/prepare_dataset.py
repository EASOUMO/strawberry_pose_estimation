"""
prepare_dataset.py
------------------
Downloads and organises public strawberry datasets into YOLO format.

Handles three sources:
  1. Roboflow Universe  – richest source; requires a free API key
  2. OpenImages v7      – requires fiftyone (pip install fiftyone)
  3. Your own RealSense D435i captures – see --own_images flag

Usage examples:
    # Roboflow only (recommended starting point)
    python prepare_dataset.py --source roboflow --api_key YOUR_KEY

    # OpenImages Strawberry class
    python prepare_dataset.py --source openimages --max_images 500

    # Merge your own labelled images into the dataset
    python prepare_dataset.py --source own --own_images /path/to/my_images

    # Full pipeline: download all sources + merge
    python prepare_dataset.py --source all --api_key YOUR_KEY

RealSense D435i capture tip:
    Use the realsense-viewer or the rs-save-to-disk example to capture
    colour frames at 640×480.  Save depth-aligned colour frames.
    Annotate with Labelme (polygon tool for stems, bbox for fruit).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# ── Roboflow download ─────────────────────────────────────────────────────────

ROBOFLOW_DATASETS = {
    "fruit_detect": {
        # Strawberry Ripeness / Detection datasets on Roboflow Universe.
        # Search: https://universe.roboflow.com/search?q=strawberry&t=metadata
        # These workspace/project/version values work with the roboflow Python SDK.
        "workspace": "strawberry-lkbcr",
        "project":   "strawberry-maturity",
        "version":    4,
        "format":    "yolov5",
        "description": "Strawberry maturity / ripeness – bounding boxes",
    },
    "fruit_detect_2": {
        "workspace": "roboflow-100",
        "project":   "strawberry-ohgbq",
        "version":    2,
        "format":    "yolov5",
        "description": "Roboflow-100 Strawberry dataset",
    },
    "stem_seg": {
        # Stem/peduncle segmentation – polygon masks.
        # Search: https://universe.roboflow.com/search?q=strawberry+stem
        "workspace": "strawberry-stem",
        "project":   "strawberry-stem-segmentation",
        "version":    1,
        "format":    "yolov8",       # YOLO polygon format
        "description": "Strawberry stem segmentation – polygon masks",
    },
}


def download_roboflow(api_key: str, target_dir: Path) -> None:
    try:
        from roboflow import Roboflow
    except ImportError:
        print("Install: pip install roboflow")
        sys.exit(1)

    rf = Roboflow(api_key=api_key)

    for name, cfg in ROBOFLOW_DATASETS.items():
        print(f"\n── Downloading: {cfg['description']} ──")
        try:
            project = rf.workspace(cfg["workspace"]).project(cfg["project"])
            version = project.version(cfg["version"])
            dataset = version.download(cfg["format"], location=str(target_dir / name))
            print(f"   Saved to: {target_dir / name}")
        except Exception as exc:
            print(f"   WARN: Could not download '{name}': {exc}")
            print(
                "   → Visit https://universe.roboflow.com/search?q=strawberry "
                "to find and export the dataset manually."
            )


# ── OpenImages download ───────────────────────────────────────────────────────

def download_openimages(target_dir: Path, max_images: int) -> None:
    """
    Download the 'Strawberry' class from Open Images v7 using FiftyOne.
    https://storage.googleapis.com/openimages/web/index.html
    """
    try:
        import fiftyone as fo
        import fiftyone.zoo as foz
    except ImportError:
        print("Install: pip install fiftyone")
        sys.exit(1)

    print(f"\n── Downloading OpenImages v7 – Strawberry class ({max_images} images) ──")

    for split in ("train", "validation", "test"):
        fo_split = "validation" if split == "val" else split
        n = max(1, max_images // 3)

        dataset = foz.load_zoo_dataset(
            "open-images-v7",
            split=fo_split,
            label_types=["detections"],
            classes=["Strawberry"],
            max_samples=n,
            dataset_name=f"oi_strawberry_{fo_split}",
        )

        out_split = "val" if split == "validation" else split
        img_dir = target_dir / "openimages" / "images" / out_split
        lbl_dir = target_dir / "openimages" / "labels" / out_split
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)

        for sample in dataset:
            img_path = Path(sample.filepath)
            dst_img = img_dir / img_path.name
            shutil.copy2(img_path, dst_img)

            w_img = sample.metadata.width
            h_img = sample.metadata.height
            lines = []
            if sample.ground_truth:
                for det in sample.ground_truth.detections:
                    if det.label.lower() != "strawberry":
                        continue
                    # FiftyOne bbox: [x, y, width, height] in relative coords
                    bx, by, bw, bh = det.bounding_box
                    cx = bx + bw / 2
                    cy = by + bh / 2
                    lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

            (lbl_dir / (img_path.stem + ".txt")).write_text("\n".join(lines))

        print(f"   {split}: {len(dataset)} images → {img_dir}")
        fo.delete_dataset(f"oi_strawberry_{fo_split}", verbose=False)


# ── Merge datasets into one YOLO folder ───────────────────────────────────────

def merge_detect_datasets(sources: list[Path], output: Path) -> None:
    """Copy all images+labels from multiple YOLO-format source dirs into one."""
    for split in ("train", "val", "test"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)

    total = 0
    for src in sources:
        for split in ("train", "val", "test"):
            src_imgs = src / "images" / split
            src_lbls = src / "labels" / split
            if not src_imgs.exists():
                continue
            for img in src_imgs.glob("*.[jp][pn]g"):
                lbl = src_lbls / (img.stem + ".txt")
                if not lbl.exists():
                    continue
                # Prefix source name to avoid filename collisions
                prefix = src.name
                shutil.copy2(img, output / "images" / split / f"{prefix}_{img.name}")
                shutil.copy2(lbl, output / "labels" / split / f"{prefix}_{img.stem}.txt")
                total += 1

    print(f"\nMerged {total} image-label pairs → {output}")


# ── Own captures helper ───────────────────────────────────────────────────────

def import_own_images(own_dir: Path, output: Path, split: str = "train") -> None:
    """
    Copy your own RealSense D435i captures + Labelme/CVAT annotations
    into the dataset.  Expects *own_dir* to already be in YOLO format:
        own_dir/images/{train,val,test}/*.jpg
        own_dir/labels/{train,val,test}/*.txt
    """
    merge_detect_datasets([own_dir], output)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare strawberry datasets")
    parser.add_argument(
        "--source",
        choices=["roboflow", "openimages", "own", "all"],
        default="roboflow",
    )
    parser.add_argument("--api_key",    default="", help="Roboflow API key")
    parser.add_argument("--max_images", type=int, default=500,
                        help="Max images to download from OpenImages")
    parser.add_argument("--own_images", default="",
                        help="Path to your own YOLO-format dataset")
    parser.add_argument(
        "--output_detect",
        default="./data/strawberry_detect",
        help="Output directory for merged detection dataset",
    )
    parser.add_argument(
        "--output_seg",
        default="./data/strawberry_seg",
        help="Output directory for stem segmentation dataset",
    )
    args = parser.parse_args()

    raw_dir = Path("./data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    sources_detect = []
    sources_seg    = []

    if args.source in ("roboflow", "all"):
        if not args.api_key:
            print("ERROR: --api_key required for Roboflow. "
                  "Get a free key at https://roboflow.com")
            sys.exit(1)
        download_roboflow(args.api_key, raw_dir)
        sources_detect += [raw_dir / "fruit_detect", raw_dir / "fruit_detect_2"]
        sources_seg    += [raw_dir / "stem_seg"]

    if args.source in ("openimages", "all"):
        download_openimages(raw_dir, args.max_images)
        sources_detect += [raw_dir / "openimages"]

    if args.source in ("own", "all") and args.own_images:
        sources_detect += [Path(args.own_images)]
        sources_seg    += [Path(args.own_images)]

    if sources_detect:
        merge_detect_datasets(sources_detect, Path(args.output_detect))
    if sources_seg:
        merge_detect_datasets(sources_seg, Path(args.output_seg))

    print("\nDone. Next steps:")
    print("  python train_detection.py")
    print("  python augment_stems.py --split train --multiplier 3")
    print("  python train_segmentation.py")


if __name__ == "__main__":
    main()
