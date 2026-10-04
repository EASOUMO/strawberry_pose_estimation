"""
augment_stems.py
----------------
Offline data augmentation for stem images, implementing the three techniques
shown in Figure 6 of Xie et al. 2024:

  (a) Original image
  (b) Rotation          – random angle ±30°
  (c) Brightness adjust – random gamma [0.5, 1.8]
  (d) Motion blur       – directional kernel, length 5–20 px, random angle

Run this BEFORE training to expand the stem dataset.  The script:
  1. Reads every image + its YOLO-SEG label from  data/strawberry_seg/
  2. Applies each of the three augmentations N times
  3. Writes augmented images + transformed labels back to the same split folder

Usage:
    python augment_stems.py --split train --multiplier 3
    # → triples the training set via augmentation

RealSense D435i note:
    Capture stems at 640×480 (native D435i resolution), then resize to 320×320
    for YOLOv5s-seg training (--imgsz 320 in training script).
    The depth frame should be aligned with the colour frame using:
        rs2::align align_to_color(RS2_STREAM_COLOR);
"""

import argparse
import random
import shutil
from pathlib import Path

import cv2
import numpy as np


# ── Augmentation primitives ───────────────────────────────────────────────────

def rotate_image_and_label(
    image: np.ndarray,
    label_lines: list[str],
    angle_deg: float,
) -> tuple[np.ndarray, list[str]]:
    """
    Rotate image and YOLO-SEG polygon labels by *angle_deg* degrees.
    YOLO-SEG label format: <class> <x1> <y1> <x2> <y2> ... (normalised)
    """
    h, w = image.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    M = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0)
    rotated = cv2.warpAffine(image, M, (w, h),
                             borderMode=cv2.BORDER_REFLECT_101)

    new_labels = []
    for line in label_lines:
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        cls = parts[0]
        coords = list(map(float, parts[1:]))
        # Reshape to (N, 2) pixel coords
        pts = np.array(coords).reshape(-1, 2)
        pts[:, 0] *= w
        pts[:, 1] *= h
        # Apply rotation matrix
        ones = np.ones((pts.shape[0], 1))
        pts_h = np.hstack([pts, ones])
        pts_rot = (M @ pts_h.T).T
        # Clamp and normalise
        pts_rot[:, 0] = np.clip(pts_rot[:, 0], 0, w) / w
        pts_rot[:, 1] = np.clip(pts_rot[:, 1], 0, h) / h
        flat = " ".join(f"{v:.6f}" for v in pts_rot.flatten())
        new_labels.append(f"{cls} {flat}")

    return rotated, new_labels


def adjust_brightness(image: np.ndarray, gamma: float) -> np.ndarray:
    """
    Apply power-law (gamma) correction to simulate brightness variation.
    output = (input / 255) ^ gamma * 255
    gamma < 1.0 → brighter  (curve bows upward)
    gamma > 1.0 → darker    (curve bows downward)
    Typical range used here: gamma ∈ [0.5, 1.8]
    """
    table = np.array(
        [(i / 255.0) ** gamma * 255 for i in range(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(image, table)


def motion_blur(image: np.ndarray, length: int, angle_deg: float) -> np.ndarray:
    """
    Convolve image with a directional motion-blur kernel.
    *length* : blur length in pixels (5–20 px recommended)
    *angle_deg* : blur direction in degrees (0 = horizontal)
    """
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0 / length
    M = cv2.getRotationMatrix2D((length / 2, length / 2), angle_deg, 1.0)
    kernel = cv2.warpAffine(kernel, M, (length, length))
    kernel /= kernel.sum() + 1e-8
    return cv2.filter2D(image, -1, kernel)


# ── Per-image augmentation pipeline ──────────────────────────────────────────

def augment_one(
    image: np.ndarray,
    label_lines: list[str],
    aug_type: str,
) -> tuple[np.ndarray, list[str]]:
    """
    Apply a single augmentation type.  Labels are only transformed for
    'rotation'; brightness and blur do not change geometry.

    aug_type: 'rotation' | 'brightness' | 'motion_blur'
    """
    if aug_type == "rotation":
        angle = random.uniform(-30.0, 30.0)
        return rotate_image_and_label(image, label_lines, angle)

    if aug_type == "brightness":
        gamma = random.uniform(0.5, 1.8)
        return adjust_brightness(image, gamma), label_lines

    if aug_type == "motion_blur":
        length = random.randint(5, 20)
        angle  = random.uniform(0, 180)
        return motion_blur(image, length, angle), label_lines

    raise ValueError(f"Unknown aug_type: {aug_type}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(data_root: Path, split: str, multiplier: int) -> None:
    img_dir = data_root / split / "images"
    lbl_dir = data_root / split / "labels"

    images = sorted(img_dir.glob("*.jpg")) + sorted(img_dir.glob("*.png"))
    print(f"Found {len(images)} original images in '{split}' split.")

    aug_types = ["rotation", "brightness", "motion_blur"]
    generated = 0

    for img_path in images:
        lbl_path = lbl_dir / (img_path.stem + ".txt")
        if not lbl_path.exists():
            continue

        image = cv2.imread(str(img_path))
        label_lines = lbl_path.read_text().splitlines()

        for rep in range(multiplier):
            aug_type = aug_types[rep % len(aug_types)]
            aug_img, aug_labels = augment_one(image, label_lines, aug_type)

            stem = f"{img_path.stem}_{aug_type}_{rep:03d}"
            out_img = img_dir / f"{stem}.jpg"
            out_lbl = lbl_dir / f"{stem}.txt"

            cv2.imwrite(str(out_img), aug_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            out_lbl.write_text("\n".join(aug_labels))
            generated += 1

    print(
        f"Generated {generated} augmented images. "
        f"Total '{split}' set: {len(images) + generated} images."
    )


ALL_TRAIN_SPLITS = ["train", "train1", "train2"]

_SCRIPTS_DIR = Path(__file__).resolve().parent
_DEFAULT_DATA_ROOT = str(_SCRIPTS_DIR.parent / "data" / "strawberry_seg")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline stem augmentation (Xie 2024, Figure 6)"
    )
    parser.add_argument(
        "--data_root",
        default=_DEFAULT_DATA_ROOT,
        help="Root of the YOLO-SEG dataset (contains train/, train1/, train2/)",
    )
    parser.add_argument(
        "--split",
        default="all",
        choices=["all", "train", "train1", "train2"],
        help="Which dataset split to augment. 'all' runs all 3 training sets.",
    )
    parser.add_argument(
        "--multiplier",
        type=int,
        default=3,
        help=(
            "How many augmented copies to generate per original image. "
            "Paper trained on 7251 stem images; use multiplier=3 with ~2400 "
            "raw captures to match that scale."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility"
    )
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)

    data_root = Path(args.data_root)
    splits = ALL_TRAIN_SPLITS if args.split == "all" else [args.split]
    for split in splits:
        print(f"\n── Augmenting split: {split} ──")
        run(data_root, split, args.multiplier)


if __name__ == "__main__":
    main()
