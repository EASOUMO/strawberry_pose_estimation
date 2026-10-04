# Strawberry Perception – Dataset Guide

## Why YOLOv5s and not YOLOv11?

This is the most important design decision to justify, because newer models
(YOLOv8, YOLOv9, YOLOv11) exist and have higher COCO benchmarks.

### Quantitative comparison

| Model       | Params | Size  | mAP50 (COCO) | Jetson NX FP16 | Jetson NX INT8 |
|-------------|--------|-------|--------------|----------------|----------------|
| YOLOv5s     | 7.2 M  | 14 MB | 37.4 %       | **~60 FPS**    | **~90 FPS**    |
| YOLOv8s     | 11.2 M | 22 MB | 44.9 %       | ~35 FPS        | ~55 FPS        |
| YOLOv9s     | 7.1 M  | 26 MB | 46.8 %       | ~30 FPS        | ~45 FPS        |
| YOLOv11s    | 9.4 M  | 18 MB | 47.0 %       | ~30 FPS        | ~48 FPS        |

*Jetson Xavier NX benchmarks at 320W mode, TensorRT optimised.*

### Reason 1 – Paper fidelity (primary reason)
Xie et al. 2024 achieved **98.0 % AP@0.5** on strawberry detection using YOLOv5s
(Table 1).  This implementation directly reproduces that pipeline.  Using a
different architecture breaks reproducibility and makes it impossible to
attribute accuracy differences to data vs. architecture.

### Reason 2 – Ceiling effect on narrow domains
COCO benchmarks measure performance across 80 diverse categories including
tiny objects, crowds, and rare classes.  YOLOv11's +9.6% COCO advantage comes
from these hard cases.  For **ripe strawberry detection specifically**:
- Single class, consistent red/orange colour, approximately round shape
- Controlled polytunnel background (black mulch + green leaves)
- Typical fruit size: 15–40 % of frame width (not tiny objects)

On this constrained domain, YOLOv5s already saturates performance at 98% AP.
The additional complexity of YOLOv11 (C2PSA attention, dynamic head) provides
**no measurable benefit** while costing 2× the inference budget.

### Reason 3 – Jetson Xavier NX is the deployment target
The paper explicitly deploys on Jetson Xavier NX with TensorRT.  The Jetson
has 384 CUDA cores and 8 GB unified memory — a constrained edge device.

- YOLOv5s runs at **~60 FPS** in FP16 on the Jetson
- YOLOv11s runs at **~30 FPS** — half the throughput

At 4.5 s per harvest cycle (paper's measured rate), the vision pipeline must
run continuously without becoming the bottleneck.  YOLOv5s gives comfortable
headroom; YOLOv11s does not.

### Reason 4 – TensorRT optimisation maturity
YOLOv5 has 3+ years of TensorRT export tooling, including:
- Official NVIDIA deep learning examples
- INT8 calibration with post-training quantization
- Well-tested `export.py` → `.engine` pipeline

YOLOv11's TensorRT export path is newer and has fewer production deployments
on Jetson specifically.

### When to upgrade to YOLOv11
Consider upgrading if:
- You deploy on a server GPU (RTX 4090 class) where throughput is not a constraint
- You observe systematic misses on partially occluded or small unripe fruits
- You have > 10,000 training images and want to squeeze out the last 1-2% AP

Even then, upgrade only the **detection** model (YOLOv5s → YOLOv11s); keep
the segmentation model at YOLOv5s-seg since the stem segmentation task is
even more constrained and the bottleneck is annotation quality, not architecture.

---

## Open-Source Datasets

### For Fruit Detection (YOLOv5s)

The paper used **2,152 fruit images**.  Combine the sources below to reach
that scale; supplement with your own RealSense D435i captures.

---

#### 1. Roboflow Universe — Strawberry collections
**URL:** https://universe.roboflow.com/search?q=strawberry&t=metadata

Roboflow hosts the largest collection of labelled strawberry datasets.
Key datasets (all free with a Roboflow account):

| Dataset | Images | Labels | Format |
|---------|--------|--------|--------|
| Strawberry Maturity | ~800 | Bounding box (ripe/unripe) | YOLOv5 |
| Strawberry Detection (roboflow-100) | ~200 | Bounding box | YOLOv5 |
| Strawberry Ripeness Detection | ~600 | Bounding box + classes | YOLOv5 |
| Strawberry Instance Seg | ~300 | Polygon masks | YOLOv8-seg |

**Download** (requires free API key from roboflow.com):
```bash
pip install roboflow
python prepare_dataset.py --source roboflow --api_key YOUR_KEY
```

**Or manually:**
1. Go to the dataset URL on Roboflow Universe
2. Click "Download" → YOLOv5 format
3. Place in `training/data/strawberry_detect/`

---

#### 2. OpenImages v7 — Strawberry class
**URL:** https://storage.googleapis.com/openimages/web/visualizer/index.html?type=detection&set=train&c=%2Fm%2F07qxg_

OpenImages v7 contains ~3,000 images with Strawberry bounding box annotations.
Images come from diverse real-world conditions (markets, fields, plates) —
useful for reducing false positives on non-field strawberries.

**Download via FiftyOne** (recommended):
```bash
pip install fiftyone
python prepare_dataset.py --source openimages --max_images 1000
```

**Download via OIDv4_ToolKit** (alternative):
```bash
git clone https://github.com/EscVM/OIDv4_ToolKit
cd OIDv4_ToolKit
python main.py downloader --classes Strawberry --type_csv train --limit 500
```

**Label class mapping:**
OpenImages class "Strawberry" → YOLO class 0 (ripe_strawberry).
The prepare_dataset.py script handles this mapping automatically.

---

#### 3. Kaggle — Fruits 360
**URL:** https://www.kaggle.com/datasets/moltean/fruits

Contains 90,000+ cropped fruit images at 100×100 px across 131 fruit classes
including multiple strawberry varieties (ripe, unripe, wedge).

**Use case:** Pre-training or transfer learning only.  Not suitable for
direct detection training because images are cropped/white-background, not
field images.  Convert to bounding box labels using the full-image wrapper
in `prepare_dataset.py` if needed.

```bash
kaggle datasets download moltean/fruits
```

---

#### 4. LADD — Large Agriculture Detection Dataset
**URL:** https://github.com/poppinace/ladd

Multi-class agricultural detection dataset including strawberries, annotated
for object detection in field conditions.

```bash
git clone https://github.com/poppinace/ladd
```

---

#### 5. Global Wheat Detection (methodology reference)
**URL:** https://www.kaggle.com/c/global-wheat-detection

Not strawberry-specific, but the largest public agricultural detection
competition dataset.  Useful for understanding domain-adaptation techniques
(different fields, lighting, growing stages) that apply equally to strawberries.

---

### For Stem Segmentation (YOLOv5s-seg)

The paper used **7,251 stem images** collected from their own experimental
site.  Public stem-specific datasets are very limited — you will need to
collect and annotate your own images with the RealSense D435i.

---

#### 6. RoboflowUniverse — Stem/Peduncle searches
**URL:** https://universe.roboflow.com/search?q=strawberry+stem

Search results are sparse but growing.  Check for datasets tagged with:
- "peduncle", "stem", "calyx", "pedicel"

These will provide polygon-annotated stem masks in YOLO-SEG format.

---

#### 7. MinneApple — Apple harvest (methodology reference)
**URL:** https://rsn.cs.umn.edu/groups/irvl/minneapple

Apple detection and segmentation dataset from field robots.  The annotation
methodology (polygon masks around stems/peduncles) directly transfers to
strawberry stem labelling.

---

#### 8. WGISD — Wine Grape Instance Segmentation Dataset
**URL:** https://github.com/thsant/wgisd

Instance segmentation masks for grape clusters in field conditions.
Demonstrates the polygon annotation format needed for YOLOv5s-seg.

---

### Your Own RealSense D435i Captures (most important)

**The paper's training images were captured with the same camera as inference.**
This is the single most impactful thing you can do to close the domain gap.

#### Capture protocol matching the paper:
```
Camera  : RealSense D435i, colour stream 640×480 @ 30 fps
Distance: 10–40 cm from the stem (end-effector approach range)
Angles  : Multiple angles per plant (paper: "multiple angles along the ridge")
Lighting: Capture on sunny, cloudy, and overcast days (3 conditions)
```

#### ROS2 capture node (save images from the live RealSense feed):
```bash
# Save colour frames to disk
ros2 run image_view image_saver --ros-args \
    -r image:=/camera/color/image_raw \
    -p filename_format:=stem_%04i.jpg \
    -p save_all_image:=false   # press 's' in the window to save

# Or record a ROS bag and extract later
ros2 bag record /camera/color/image_raw /camera/depth/image_rect_raw
```

#### D435i-specific settings for training:
```python
import pyrealsense2 as rs

pipeline = rs.pipeline()
config   = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

# Align depth to colour (required for 3D picking point extraction)
align = rs.align(rs.stream.color)

# D435i IMU streams (optional — for motion compensation during capture)
config.enable_stream(rs.stream.accel)
config.enable_stream(rs.stream.gyro)
```

#### Annotation workflow:
```bash
# Install Labelme
pip install labelme

# Open Labelme with polygon tool
labelme ./my_captured_stems/

# For stems: use polygon, label = "stem"
# For fruit:  use rectangle, labels = "ripe_strawberry" / "unripe_strawberry"

# Convert Labelme JSON → YOLO format
pip install labelme2yolo
labelme2yolo --json_dir ./my_captured_stems/ --val_size 0.1 --test_size 0.1
```

---

## Recommended Dataset Assembly

### For fruit detection (target: ~2,152 images)
```
Source                     Images    Notes
─────────────────────────  ──────    ──────────────────────────────────────
Roboflow Strawberry sets   ~1,600    Download and merge 2–3 datasets
OpenImages v7              ~300      Diverse backgrounds, reduces false pos.
Your D435i captures        ~300      Same camera + lighting as deployment
─────────────────────────  ──────
Total                      ~2,200    Matches paper's training set size
```

### For stem segmentation (target: ~7,251 images after augmentation)
```
Source                           Raw     After augment_stems.py (×3)
──────────────────────────────   ─────   ──────────────────────────────
Your D435i stem captures         ~2,400  ~7,200 (rotation + brightness + blur)
Roboflow stem/peduncle datasets  ~50     ~150
──────────────────────────────   ─────   ──────────────────────────────
Total                            ~2,450  ~7,350  ← matches paper
```

**Key takeaway:** For stems, collect ~2,400 raw images with your D435i at
10–40 cm distance, annotate polygons with Labelme, then run `augment_stems.py`
with `--multiplier 3` to expand to the paper's 7,251 image scale.

---

## Training Pipeline Summary

```bash
# 1. Download public datasets
cd training/scripts
python prepare_dataset.py --source roboflow --api_key YOUR_KEY
python prepare_dataset.py --source openimages --max_images 500

# 2. Add your own D435i captures (after Labelme annotation)
python prepare_dataset.py --source own --own_images /path/to/my_dataset

# 3. Create val/test splits from all 3 datasets (REQUIRED before training)
#    Moves 10% of each of train/, train1/, train2/ → val/ and test/
python split_datasets.py

# 4. Augment ALL 3 training sets to reach paper's 7,251 scale
python augment_stems.py --split all --multiplier 3

# 5. Train detection model (paper: 300 epochs, 640px, batch 40)
python train_detection.py

# 6. Train segmentation model on combined 3-dataset config (300 epochs, 320px, batch 60)
python train_segmentation.py

# 7. Validate against paper benchmarks
python validate.py --weights runs/detect/strawberry_yolov5s/weights/best.pt
#    Validate segmentation on each of the 3 datasets individually:
python validate.py --weights runs/segment/stem_yolov5s_seg/weights/best.pt \
                   --task segment --data all

# 8. Export to TensorRT (run ON the Jetson Xavier NX)
python export_tensorrt.py --weights runs/detect/.../best.pt --task detect
python export_tensorrt.py --weights runs/segment/.../best.pt --task segment --imgsz 320

# 9. Launch the ROS2 perception node with TensorRT engines
ros2 launch strawberry_perception perception.launch.py \
    det_weights:=/path/to/detect.engine \
    seg_weights:=/path/to/segment.engine \
    device:=0
```
