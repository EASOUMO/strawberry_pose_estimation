"""
stem_localizer.py
-----------------
Extracts the picking point and stem tilt angle from a binary stem mask.

Algorithm (Section 2.4, Xie et al. 2024):

  1. Midline extraction
     For every row that contains mask pixels, compute the horizontal
     centre-of-mass → gives an ordered set of (row, col) points tracing
     the stem skeleton from top to bottom.

  2. Picking point selection
     "counting upwards from the bottom, the 30th pixel is designated
     as the picking point."
     → midline sorted descending by row, index 29 (0-based).

  3. Local point set
     "obtained by expanding 15 pixels on both sides of the picking point."
     → midline[14 : 45] in the bottom-up sorted array.

  4. Slope / tilt angle
     "the stem's tilt direction is determined by fitting the pixel sets on
     both sides of this point."
     → np.polyfit(rows, cols, 1) on the local point set.
     → angle_deg = arctan(slope) where slope = d_col / d_row.
     A vertical stem gives angle_deg ≈ 0°.
"""

from typing import Optional, Tuple

import cv2
import numpy as np


class StemLocalizer:
    # Paper-defined constants (Section 2.4), calibrated at the paper's stated
    # capture resolution of 640x480 ("Using the RGB camera with a resolution
    # of 640 x 480..."). Scaled at runtime by image height / REF_HEIGHT so the
    # same physical ~10mm stem remnant is used regardless of the camera's
    # actual configured resolution (e.g. a D435i running at 1280x720).
    REF_HEIGHT: int = 480
    PICK_IDX_FROM_BOTTOM: int = 30   # "30th pixel from the bottom" @ 640x480
    LOCAL_HALF_WINDOW: int = 15      # "15 pixels on both sides" @ 640x480

    # Absolute floor on midline length, independent of the scaled pick index
    # below -- short/noisy masks are still rejected, but a real stem shorter
    # than the *scaled* ideal index no longer gets discarded outright (see
    # compute()). At this project's actual deployed camera resolution
    # (D435i/D455F both default to 1280x720), the scaled index works out to
    # ~80px while real segmented stems in this project's own training data
    # are typically 15-150px long, so the old hard reject was silently
    # dropping the large majority of valid detections.
    MIN_MIDLINE_LEN: int = 5

    # ── Public API ────────────────────────────────────────────────────────────

    def compute(
        self, mask: np.ndarray
    ) -> Optional[Tuple[int, int, float]]:
        """
        Parameters
        ----------
        mask : uint8 binary mask (H × W), 255 = stem pixel.

        Returns
        -------
        (u_pick, v_pick, angle_deg) or None if the midline is below
        MIN_MIDLINE_LEN.

        u_pick    – column (x) of the picking point in image coordinates
        v_pick    – row    (y) of the picking point in image coordinates
        angle_deg – stem tilt in degrees (0 = perfectly vertical stem,
                    positive = tilted right, negative = tilted left)
        """
        midline = self._extract_midline(mask)
        if midline is None or len(midline) < self.MIN_MIDLINE_LEN:
            return None

        # Scale the paper's pixel-count constants to the actual image
        # resolution (they were calibrated at 640x480; see REF_HEIGHT).
        scale = mask.shape[0] / float(self.REF_HEIGHT)
        pick_idx_from_bottom = max(1, round(self.PICK_IDX_FROM_BOTTOM * scale))
        local_half_window = max(1, round(self.LOCAL_HALF_WINDOW * scale))

        # If the segmented stem is shorter than the ideal scaled pick index,
        # use the topmost available midline pixel instead of discarding the
        # detection outright -- see MIN_MIDLINE_LEN above for why this
        # matters at this project's actual deployed resolution.
        pick_idx_from_bottom = min(pick_idx_from_bottom, len(midline))

        # Sort rows descending → index 0 is the bottom-most midline pixel
        order = np.argsort(midline[:, 0])[::-1]
        midline_btm_up = midline[order]

        # ── Picking point (paper: 30th from bottom, scaled) ───────────────
        pick_idx = pick_idx_from_bottom - 1
        pick = midline_btm_up[pick_idx]
        v_pick = int(round(pick[0]))   # row
        u_pick = int(round(pick[1]))   # col

        # ── Local point set (±half-window pixels around picking point) ───
        lo = max(0, pick_idx - local_half_window)
        hi = min(
            len(midline_btm_up),
            pick_idx + local_half_window + 1,
        )
        local_pts = midline_btm_up[lo:hi]

        # ── Fit line → slope → tilt angle ────────────────────────────────
        if len(local_pts) >= 2:
            rows = local_pts[:, 0].astype(float)
            cols = local_pts[:, 1].astype(float)
            # col = a * row + b  →  slope a = d_col / d_row
            coeffs = np.polyfit(rows, cols, deg=1)
            slope = float(coeffs[0])
            angle_deg = float(np.degrees(np.arctan(slope)))
        else:
            angle_deg = 0.0

        return u_pick, v_pick, angle_deg

    # ── Visualisation helper ──────────────────────────────────────────────────

    def visualize(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        u_pick: int,
        v_pick: int,
        angle_deg: float,
    ) -> np.ndarray:
        """
        Draw stem mask overlay, midline skeleton, picking point, and tilt
        angle annotation onto *image*.  Returns the annotated copy.
        """
        vis = image.copy()

        # Green mask overlay (40 % transparency)
        overlay = vis.copy()
        overlay[mask > 0] = (0, 200, 0)
        cv2.addWeighted(overlay, 0.4, vis, 0.6, 0, vis)

        # Yellow midline dots
        midline = self._extract_midline(mask)
        if midline is not None:
            for row, col in midline.astype(int):
                cv2.circle(vis, (col, row), 1, (0, 255, 255), -1)

        # Picking point: red filled circle with white ring
        cv2.circle(vis, (u_pick, v_pick), 6, (0, 0, 255), -1)
        cv2.circle(vis, (u_pick, v_pick), 9, (255, 255, 255), 2)

        # Tilt direction line through the picking point
        length = 30
        dx = int(length * np.sin(np.radians(angle_deg)))
        dy = int(length * np.cos(np.radians(angle_deg)))
        cv2.line(
            vis,
            (u_pick - dx, v_pick - dy),
            (u_pick + dx, v_pick + dy),
            (255, 128, 0),
            2,
        )

        # Text annotation
        cv2.putText(
            vis,
            f"stem {angle_deg:+.1f}deg",
            (u_pick + 12, v_pick - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return vis

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract_midline(self, mask: np.ndarray) -> Optional[np.ndarray]:
        """
        For each row containing at least one mask pixel, compute the
        horizontal centre between the leftmost and rightmost set pixel.

        Returns
        -------
        np.ndarray shape (N, 2) with columns [row, col], or None.
        """
        points = []
        for row_idx in range(mask.shape[0]):
            cols_on = np.flatnonzero(mask[row_idx] > 0)
            if cols_on.size == 0:
                continue
            centre_col = (float(cols_on[0]) + float(cols_on[-1])) / 2.0
            points.append([float(row_idx), centre_col])

        return np.array(points, dtype=float) if points else None
