#!/usr/bin/env python3
"""
detection_node.py
-----------------
ROS2 node implementing the full Xie et al. 2024 picking-point localisation
pipeline:

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  Camera image          YOLOv5s            Expand RoI ×1.5               │
  │  ─────────────  ──►  detection   ──►  ─────────────────────────────     │
  │  /camera/color/        (fruit)          YOLOv5s-seg (stem mask)         │
  │  image_raw                                     │                        │
  │                                                ▼                        │
  │  /camera/depth/    Midline → 30th px    Slope via polyfit               │
  │  image_rect_raw    from bottom =        (local ±15 px window)           │
  │                    picking point (u,v)         │                        │
  │                         │                      ▼                        │
  │                         └──────► pixel_to_camera_frame()                │
  │                                      (intrinsics from CameraInfo)       │
  │                                           │                             │
  │                                           ▼                             │
  │                                  camera_to_robot_frame()  (TF2)         │
  │                                           │                             │
  │                                           ▼                             │
  │                         /strawberry/picking_pose  (PoseStamped)         │
  │                         /strawberry/picking_markers (MarkerArray)       │
  │                         /strawberry/detection_image (debug Image)       │
  └──────────────────────────────────────────────────────────────────────────┘

ROS parameters (set in config/perception_params.yaml):
  det_weights          path to YOLOv5s  detection weights (.pt)
  seg_weights          path to YOLOv5s-seg segmentation weights (.pt)
  device               'cpu' or 'cuda:0'
  camera_frame         TF source frame  (default: camera_color_optical_frame)
  robot_frame          TF target frame  (default: base_link)
  color_topic          RGB image topic  (default: /camera/color/image_raw)
  depth_topic          Depth image topic (default: /camera/depth/image_rect_raw)
  camera_info_topic    CameraInfo topic (default: /camera/color/camera_info)
  publish_debug        publish annotated debug image (default: true)
"""

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from visualization_msgs.msg import Marker, MarkerArray
import message_filters
import tf2_ros

from .coordinate_transform import (
    camera_to_robot_frame,
    pixel_to_camera_frame,
    stem_angle_to_quaternion,
)
from .stem_localizer import StemLocalizer
from .yolo_detector import YoloDetector


class StrawberryPerceptionNode(Node):

    def __init__(self):
        super().__init__("strawberry_perception")

        # ── Declare ROS parameters ────────────────────────────────────────
        self.declare_parameter("det_weights",       "/home/ubuntu/base_ws/src/strawberry_pose_estimation/src/strawberry_perception/training/scripts/runs/detect/runs/detect/strawberry_yolov5s/weights/best.pt")
        self.declare_parameter("seg_weights",       "/home/ubuntu/base_ws/src/strawberry_pose_estimation/src/strawberry_perception/training/scripts/runs/segment/stem_yolov5s_seg-4/weights/best.pt")
        self.declare_parameter("device",            "cpu")
        self.declare_parameter("camera_frame",      "camera_color_optical_frame")
        self.declare_parameter("robot_frame",       "base_link")
        self.declare_parameter("color_topic",       "/camera/color/image_raw")
        self.declare_parameter("depth_topic",       "/camera/depth/image_rect_raw")
        self.declare_parameter("camera_info_topic", "/camera/color/camera_info")
        self.declare_parameter("publish_debug",     True)

        det_w       = self.get_parameter("det_weights").value
        seg_w       = self.get_parameter("seg_weights").value
        device      = self.get_parameter("device").value
        self._cam_frame   = self.get_parameter("camera_frame").value
        self._robot_frame = self.get_parameter("robot_frame").value
        color_topic       = self.get_parameter("color_topic").value
        depth_topic       = self.get_parameter("depth_topic").value
        info_topic        = self.get_parameter("camera_info_topic").value
        pub_debug         = self.get_parameter("publish_debug").value

        # ── Sub-systems ───────────────────────────────────────────────────
        self._detector  = YoloDetector(det_w, seg_w, device)
        self._localizer = StemLocalizer()
        self._bridge    = CvBridge()
        self._K: dict | None = None   # populated once from CameraInfo

        self._tf_buffer   = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        # ── Publishers ────────────────────────────────────────────────────
        self._pub_pose    = self.create_publisher(
            PoseStamped,  "/strawberry/picking_pose",    10)
        self._pub_markers = self.create_publisher(
            MarkerArray,  "/strawberry/picking_markers", 10)
        self._pub_debug   = (
            self.create_publisher(Image, "/strawberry/detection_image", 10)
            if pub_debug else None
        )

        # ── CameraInfo – read once, then unsubscribe ──────────────────────
        self._info_sub = self.create_subscription(
            CameraInfo, info_topic, self._camera_info_cb, 1
        )

        # ── Time-synchronised image subscribers ───────────────────────────
        color_sub = message_filters.Subscriber(self, Image, color_topic)
        depth_sub = message_filters.Subscriber(self, Image, depth_topic)
        self._sync = message_filters.ApproximateTimeSynchronizer(
            [color_sub, depth_sub], queue_size=5, slop=0.05
        )
        self._sync.registerCallback(self._image_cb)
        self._color_topic = color_topic
        self._depth_topic = depth_topic

        # ── Watchdog: warn if no synced frame has arrived in a while ──────
        # A stalled synchronizer (e.g. a depth-topic subscription that never
        # reconnected after the camera driver briefly had zero publishers,
        # or the camera simply not running) otherwise looks identical to
        # "everything is fine, just no strawberries in frame" -- both
        # produce total silence on every output topic, and previously
        # required manually probing topic publisher counts and stream
        # timestamps to tell apart. This surfaces the distinction directly
        # in the node's own log.
        self._last_frame_time = self.get_clock().now()
        self.create_timer(5.0, self._watchdog_cb)

        self.get_logger().info(
            "StrawberryPerceptionNode ready.\n"
            f"  color : {color_topic}\n"
            f"  depth : {depth_topic}\n"
            f"  frames: {self._cam_frame} → {self._robot_frame}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sample_depth(
        depth_m: np.ndarray, u: int, v: int, bbox,
        radius: int = 5, stem_mask: np.ndarray = None,
    ):
        """Return depth for the picking point.

        Defaults to the median depth over the fruit's own bounding box --
        berry and stem sit at approximately the same distance from the
        camera, and the bbox is a much larger, more stable region than a
        single point on a thin stem (which frequently lands on a depth
        hole). Falls back to a (2r+1)x(2r+1) window around (u,v), then the
        stem mask itself, only if the bbox somehow yields no valid depth
        at all. None if nothing yields a valid reading.
        """
        h, w = depth_m.shape

        x1, y1, x2, y2 = bbox
        bbox_patch = depth_m[max(0, y1):min(h, y2), max(0, x1):min(w, x2)].ravel()
        valid_bbox = bbox_patch[(bbox_patch > 0.01) & np.isfinite(bbox_patch)]
        if valid_bbox.size > 0:
            return float(np.median(valid_bbox))

        v0, v1 = max(0, v - radius), min(h, v + radius + 1)
        u0, u1 = max(0, u - radius), min(w, u + radius + 1)
        patch = depth_m[v0:v1, u0:u1].ravel()
        valid = patch[(patch > 0.01) & np.isfinite(patch)]
        if valid.size > 0:
            return float(np.median(valid))

        if stem_mask is not None:
            mask_vals = depth_m[stem_mask > 0].ravel()
            valid_mask = mask_vals[(mask_vals > 0.01) & np.isfinite(mask_vals)]
            if valid_mask.size > 0:
                return float(np.median(valid_mask))

        return None

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _camera_info_cb(self, msg: CameraInfo) -> None:
        """Store camera intrinsics and unsubscribe (they don't change)."""
        if self._K is not None:
            return
        k = msg.k  # row-major 3×3 intrinsic matrix
        self._K = {"fx": k[0], "fy": k[4], "cx": k[2], "cy": k[5]}
        self.get_logger().info(
            f"Camera intrinsics: fx={k[0]:.1f} fy={k[4]:.1f} "
            f"cx={k[2]:.1f} cy={k[5]:.1f}"
        )
        self.destroy_subscription(self._info_sub)

    def _watchdog_cb(self) -> None:
        """Runs every 5s. Distinguishes "no strawberries in frame" (normal,
        stays silent) from "the synchronizer isn't firing at all" (a stall
        that otherwise looks identical from the outside -- every output
        topic just goes quiet)."""
        stalled_for = (self.get_clock().now() - self._last_frame_time).nanoseconds / 1e9
        if stalled_for < 8.0:
            return
        if self._K is None:
            self.get_logger().warn(
                f"No CameraInfo received on the camera_info topic in "
                f"{stalled_for:.0f}s -- is the camera driver running?",
                throttle_duration_sec=15,
            )
        else:
            self.get_logger().warn(
                f"No synchronized color+depth frame in {stalled_for:.0f}s "
                "(camera intrinsics were received, so this isn't a startup "
                "race). The synchronizer callback isn't firing. Check: "
                f"'ros2 topic info {self._depth_topic} --verbose' for zero "
                "publishers, or a stale subscription left over from a "
                "camera driver that was restarted after this node started "
                "-- if so, restart this node.",
                throttle_duration_sec=15,
            )

    def _image_cb(self, color_msg: Image, depth_msg: Image) -> None:
        self._last_frame_time = self.get_clock().now()
        if self._K is None:
            self.get_logger().warn(
                "Waiting for camera intrinsics …", throttle_duration_sec=5
            )
            return

        # ── Decode images ─────────────────────────────────────────────────
        bgr   = self._bridge.imgmsg_to_cv2(color_msg, desired_encoding="bgr8")
        depth = self._bridge.imgmsg_to_cv2(depth_msg, desired_encoding="passthrough")

        # RealSense D435 depth is uint16 in millimetres → convert to metres
        if depth.dtype == np.uint16:
            depth_m = depth.astype(np.float32) / 1000.0
        else:
            depth_m = depth.astype(np.float32)

        stamp      = color_msg.header.stamp
        debug_img  = bgr.copy()
        markers    = MarkerArray()
        marker_id  = 0

        # ══════════════════════════════════════════════════════════════════
        # Step 1 – YOLOv5s: detect ripe strawberries
        # ══════════════════════════════════════════════════════════════════
        detections = self._detector.detect_strawberries(bgr)
        # Already sorted high-to-low confidence by the detector.

        img_h, img_w = bgr.shape[:2]
        # 4px reference margin @ 640px width; scaled so the same physical
        # margin applies regardless of the camera's configured resolution.
        SIDE_MARGIN = max(1, round(4 * img_w / 640.0))

        for det in detections:
            x1, y1, x2, y2, conf = det
            bbox_h = y2 - y1

            cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                debug_img, f"ripe {conf:.2f}",
                (x1, max(0, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA,
            )

            # Skip berries whose bbox is clipped by the image boundary -- the
            # stem (above the fruit) would be partly/fully outside the
            # expanded RoI, producing an incomplete/wrong stem mask and a
            # garbage picking point with no other indication of failure.
            clipped = (
                y1 < bbox_h                       # stem above frame (top clip)
                or y2 >= img_h - SIDE_MARGIN       # berry cut off at bottom
                or x1 <= SIDE_MARGIN               # berry cut off at left
                or x2 >= img_w - SIDE_MARGIN       # berry cut off at right
            )
            if clipped:
                self.get_logger().debug(
                    f"Step 2 SKIP – bbox ({x1},{y1},{x2},{y2}) clipped by "
                    f"image edge ({img_w}x{img_h}); stem likely not visible."
                )
                continue

            # ══════════════════════════════════════════════════════════════
            # Step 2 – YOLOv5s-seg: segment stem inside expanded RoI (×1.5)
            # ══════════════════════════════════════════════════════════════
            stem_mask = self._detector.segment_stem(bgr, det)
            if stem_mask is None:
                self.get_logger().debug(f"No stem mask for bbox ({x1},{y1},{x2},{y2})")
                continue

            # ══════════════════════════════════════════════════════════════
            # Step 3 – Picking point + slope
            #   • 30th pixel from the bottom of the midline
            #   • ±15 px local window → np.polyfit → tilt angle
            # ══════════════════════════════════════════════════════════════
            result = self._localizer.compute(stem_mask)
            if result is None:
                self.get_logger().debug("Midline too short – skipping.")
                continue
            u_p, v_p, angle_deg = result

            # ══════════════════════════════════════════════════════════════
            # Step 4 – Pixel (u,v) + depth → 3-D in camera optical frame
            # ══════════════════════════════════════════════════════════════
            z_m = self._sample_depth(
                depth_m, u_p, v_p, (x1, y1, x2, y2), stem_mask=stem_mask
            )
            if z_m is None:
                self.get_logger().debug(
                    f"Step 4 FAIL – no valid depth anywhere in bbox/window/"
                    f"mask at ({u_p},{v_p})."
                )
                continue

            x_c, y_c, z_c = pixel_to_camera_frame(u_p, v_p, z_m, **self._K)

            # ══════════════════════════════════════════════════════════════
            # Step 5 – Camera frame → robot base_link via TF2
            # ══════════════════════════════════════════════════════════════
            pt_robot = camera_to_robot_frame(
                x_c, y_c, z_c,
                self._cam_frame, self._robot_frame, self._tf_buffer,
            )
            if pt_robot is None:
                self.get_logger().warn(
                    f"TF unavailable: {self._cam_frame} → {self._robot_frame}",
                    throttle_duration_sec=2,
                )
                continue
            x_r, y_r, z_r = pt_robot

            # ══════════════════════════════════════════════════════════════
            # Step 6 – Build approach orientation from stem tilt angle
            # ══════════════════════════════════════════════════════════════
            qx, qy, qz, qw = stem_angle_to_quaternion(angle_deg)

            # ── Publish PoseStamped ───────────────────────────────────────
            pose_msg = PoseStamped()
            pose_msg.header.stamp    = stamp
            pose_msg.header.frame_id = self._robot_frame
            pose_msg.pose.position.x = x_r
            pose_msg.pose.position.y = y_r
            pose_msg.pose.position.z = z_r
            pose_msg.pose.orientation.x = qx
            pose_msg.pose.orientation.y = qy
            pose_msg.pose.orientation.z = qz
            pose_msg.pose.orientation.w = qw
            self._pub_pose.publish(pose_msg)

            # ── Publish RViz sphere marker at picking point ───────────────
            m = Marker()
            m.header.stamp    = stamp
            m.header.frame_id = self._robot_frame
            m.ns     = "picking_points"
            m.id     = marker_id
            marker_id += 1
            m.type   = Marker.SPHERE
            m.action = Marker.ADD
            m.pose   = pose_msg.pose
            m.scale.x = m.scale.y = m.scale.z = 0.02   # 2 cm sphere
            m.color.r = 1.0
            m.color.g = 0.2
            m.color.b = 0.2
            m.color.a = 1.0
            markers.markers.append(m)

            # ── Annotate debug image ──────────────────────────────────────
            debug_img = self._localizer.visualize(
                debug_img, stem_mask, u_p, v_p, angle_deg
            )
            cv2.putText(
                debug_img,
                f"3D ({x_r:.3f}, {y_r:.3f}, {z_r:.3f}) m",
                (x1, y2 + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 0), 1, cv2.LINE_AA,
            )

        # ── Publish markers and debug image ───────────────────────────────
        self._pub_markers.publish(markers)
        if self._pub_debug is not None:
            self._pub_debug.publish(
                self._bridge.cv2_to_imgmsg(debug_img, encoding="bgr8")
            )


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = StrawberryPerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
