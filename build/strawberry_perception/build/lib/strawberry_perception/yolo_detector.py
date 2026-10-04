"""
yolo_detector.py
----------------
Wraps YOLOv5s (object detection) and YOLOv5s-seg (instance segmentation)
following Xie et al. 2024, Section 2.4 – "Picking Point Localisation".

Detection model  : YOLOv5s  – locates ripe strawberries, outputs bounding boxes.
Segmentation model: YOLOv5s-seg – delineates the stem contour inside an
                    expanded RoI (×1.5 the fruit bounding box).

Confidence thresholds from Table 1 / Section 2.4 of the paper:
    YOLOv5s      : conf = 0.25  (precision 97.6 %, recall 93.7 %, AP 98.0 %)
    YOLOv5s-seg  : conf = 0.01  (precision 92.5 %, recall 86.6 %, AP 93.4 %)
"""

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class YoloDetector:
    # ── Hyper-parameters from the paper ──────────────────────────────────────
    DET_CONF: float = 0.25   # fruit detection confidence threshold
    SEG_CONF: float = 0.01   # stem segmentation confidence threshold
    ROI_EXPAND: float = 1.5  # RoI expansion factor (Section 2.4)

    def __init__(self, det_weights: str, seg_weights: str, device: str = "cpu"):
        """
        Parameters
        ----------
        det_weights : path to YOLOv5s weights (.pt) for fruit detection
        seg_weights : path to YOLOv5s-seg weights (.pt) for stem segmentation
        device      : 'cpu' or 'cuda:0'
        """
        self._ready = False
        try:
            from ultralytics import YOLO  # pip install ultralytics

            self._det_model = YOLO(det_weights)
            self._seg_model = YOLO(seg_weights)
            self._det_model.to(device)
            self._seg_model.to(device)
            self._ready = True
            logger.info(
                "YOLOv5s detection + YOLOv5s-seg segmentation models loaded "
                f"on {device}."
            )
        except Exception as exc:
            logger.warning(
                f"Could not load YOLO models ({exc}). "
                "Node will run in stub mode – no detections will be produced "
                "until valid weights are provided via the 'det_weights' and "
                "'seg_weights' ROS parameters."
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def detect_strawberries(
        self, image: np.ndarray
    ) -> List[Tuple[int, int, int, int, float]]:
        """
        Run YOLOv5s on *image* and return all ripe-strawberry detections.

        Returns
        -------
        list of (x1, y1, x2, y2, confidence) in pixel coordinates,
        sorted by confidence descending (high-to-low priority as per paper).
        """
        if not self._ready:
            return []

        results = self._det_model.predict(
            image, conf=self.DET_CONF, verbose=False
        )
        detections: List[Tuple[int, int, int, int, float]] = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0])
                detections.append((x1, y1, x2, y2, conf))

        detections.sort(key=lambda d: d[4], reverse=True)
        return detections

    def segment_stem(
        self,
        image: np.ndarray,
        bbox: Tuple[int, int, int, int, float],
    ) -> Optional[np.ndarray]:
        """
        Run YOLOv5s-seg on the region of interest around *bbox* to
        delineate the stem mask.

        RoI definition (Section 2.4, Xie 2024):
            "the width and height of the fruit's bounding box are expanded
            to 1.5 times to define the region of interest for the stem."

        Parameters
        ----------
        image : full BGR image (H × W × 3)
        bbox  : (x1, y1, x2, y2, conf) from detect_strawberries()

        Returns
        -------
        Binary mask np.ndarray uint8 (H × W), same size as *image*,
        with 255 where the stem was detected, or None if no stem found.
        """
        if not self._ready:
            return None

        ih, iw = image.shape[:2]
        x1, y1, x2, y2 = bbox[:4]

        # Expand RoI by ROI_EXPAND factor around the bbox centre
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        half_w = (x2 - x1) * self.ROI_EXPAND / 2.0
        half_h = (y2 - y1) * self.ROI_EXPAND / 2.0
        rx1 = max(0, int(cx - half_w))
        ry1 = max(0, int(cy - half_h))
        rx2 = min(iw, int(cx + half_w))
        ry2 = min(ih, int(cy + half_h))

        roi = image[ry1:ry2, rx1:rx2]
        if roi.size == 0:
            return None

        results = self._seg_model.predict(roi, conf=self.SEG_CONF, verbose=False)
        if not results or results[0].masks is None:
            return None

        # Pick the highest-confidence STEM detection inside the RoI.
        # The RoI is centred on the berry, so the model's other class
        # (strawberry, class 1) is often re-detected here too, sometimes with
        # higher confidence than the thinner/harder peduncle (class 0). Must
        # filter to class 0 first, or "highest confidence" can silently
        # select a strawberry mask instead of the stem.
        masks = results[0].masks.data.cpu().numpy()   # (N, roi_H, roi_W)
        cls   = results[0].boxes.cls.cpu().numpy().astype(int)
        confs = results[0].boxes.conf.cpu().numpy()

        peduncle_idx = np.where(cls == 0)[0]  # class 0 = peduncle/stem
        if len(peduncle_idx) == 0:
            return None
        best = peduncle_idx[int(np.argmax(confs[peduncle_idx]))]
        mask_roi = (masks[best] > 0.5).astype(np.uint8) * 255

        # Resize mask back to the RoI pixel dimensions
        roi_h = ry2 - ry1
        roi_w = rx2 - rx1
        mask_roi = cv2.resize(
            mask_roi, (roi_w, roi_h), interpolation=cv2.INTER_NEAREST
        )

        # Clean the raw mask: morphological opening removes isolated noise
        # specks (SEG_CONF=0.01 is permissive), then keep only the largest
        # connected blob. Stray pixels would otherwise wobble the per-row
        # midline used for picking-point/tilt-angle localisation.
        mask_roi = cv2.morphologyEx(mask_roi, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n_labels, labels = cv2.connectedComponents(mask_roi)
        if n_labels > 1:
            sizes = [int(np.sum(labels == i)) for i in range(1, n_labels)]
            largest = 1 + int(np.argmax(sizes))
            mask_roi = np.where(labels == largest, 255, 0).astype(np.uint8)

        # Place the RoI mask back onto a full-image canvas
        full_mask = np.zeros((ih, iw), dtype=np.uint8)
        full_mask[ry1:ry2, rx1:rx2] = mask_roi
        return full_mask

    @property
    def is_ready(self) -> bool:
        return self._ready
