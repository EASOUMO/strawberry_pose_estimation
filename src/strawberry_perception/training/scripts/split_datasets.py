"""
split_datasets.py
-----------------
Create val/ and test/ splits from the 3 training datasets.

The 3 training sets (train/, train1/, train2/) have no val or test splits.
YOLO training requires a val set; this script creates them.

Splits 10% of each dataset into val and 10% into test, leaving 80% for train.
The val and test images are moved (not copied) from the train folders so YOLO
does not train and evaluate on the same images.

Usage:
    python split_datasets.py                       # default 80/10/10
    python split_datasets.py --val_frac 0.15       # 70/15/15

Run ONCE before train_segmentation.py.
"""

import argparse
import random
import shutil
from pathlib import Path


TRAIN_SPLITS = ["train", "train1", "train2"]

_SCRIPTS_DIR = Path(__file__).resolve().parent
_DEFAULT_DATA_ROOT = str(_SCRIPTS_DIR.parent / "data" / "strawberry_seg")


def split_one(data_root: Path, split_name: str, val_frac: float, test_frac: float,
              seed: int) -> None:
    src_img = data_root / split_name / "images"
    src_lbl = data_root / split_name / "labels"

    images = sorted(src_img.glob("*.jpg")) + sorted(src_img.glob("*.png"))
    if not images:
        print(f"  WARNING: no images found in {src_img}, skipping.")
        return

    rng = random.Random(seed)
    rng.shuffle(images)

    n = len(images)
    n_test = max(1, int(n * test_frac))
    n_val  = max(1, int(n * val_frac))

    test_imgs = images[:n_test]
    val_imgs  = images[n_test:n_test + n_val]
    # remaining images stay in train

    dst_val_img  = data_root / "val"  / "images"
    dst_val_lbl  = data_root / "val"  / "labels"
    dst_test_img = data_root / "test" / "images"
    dst_test_lbl = data_root / "test" / "labels"
    for d in (dst_val_img, dst_val_lbl, dst_test_img, dst_test_lbl):
        d.mkdir(parents=True, exist_ok=True)

    def _move(img_path: Path, dst_img_dir: Path, dst_lbl_dir: Path) -> None:
        lbl_path = src_lbl / (img_path.stem + ".txt")
        shutil.move(str(img_path), dst_img_dir / img_path.name)
        if lbl_path.exists():
            shutil.move(str(lbl_path), dst_lbl_dir / (img_path.stem + ".txt"))

    for img in val_imgs:
        _move(img, dst_val_img, dst_val_lbl)
    for img in test_imgs:
        _move(img, dst_test_img, dst_test_lbl)

    print(f"  {split_name}: {n} total → {n - n_val - n_test} train / "
          f"{n_val} val / {n_test} test")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create val/test splits for seg datasets")
    parser.add_argument("--data_root", default=_DEFAULT_DATA_ROOT)
    parser.add_argument("--val_frac",  type=float, default=0.10)
    parser.add_argument("--test_frac", type=float, default=0.10)
    parser.add_argument("--seed",      type=int,   default=42)
    args = parser.parse_args()

    data_root = Path(args.data_root)
    print(f"Splitting datasets in {data_root}  "
          f"(val={args.val_frac:.0%}, test={args.test_frac:.0%})")

    for split in TRAIN_SPLITS:
        split_one(data_root, split, args.val_frac, args.test_frac, args.seed)

    print("\nDone. val/ and test/ are ready.")
    print("Next: python augment_stems.py --split all --multiplier 3")
    print("Then: python train_segmentation.py")


if __name__ == "__main__":
    main()
