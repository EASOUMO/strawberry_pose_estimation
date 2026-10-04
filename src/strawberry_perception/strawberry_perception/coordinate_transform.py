"""
coordinate_transform.py
------------------------
Two-stage coordinate transformation used in Xie et al. 2024:

  Stage 1 – Pixel → Camera frame
    Standard pinhole back-projection using the RealSense D435 intrinsics
    obtained from the /camera/color/camera_info topic:

        X_c = (u - c_x) * Z / f_x
        Y_c = (v - c_y) * Z / f_y
        Z_c = Z   (metric depth from the depth image)

  Stage 2 – Camera frame → Robot base_link frame
    TF2 lookup:  camera_color_optical_frame → base_link
    This transform is broadcast by the robot description / URDF.

  Approach orientation
    The 2-D stem tilt angle is converted to a 3-D approach quaternion so
    that the gripper aligns with the stem axis at the picking point.
    Convention: gripper Z-axis points along the approach direction;
                a vertical stem → gripper points straight down.
"""

from typing import Optional, Tuple

import numpy as np
import rclpy
import rclpy.duration
import tf2_geometry_msgs  # noqa: F401 – registers the PointStamped transformer
import tf2_ros
from geometry_msgs.msg import PointStamped


# ── Stage 1: Pixel → Camera optical frame ────────────────────────────────────

def pixel_to_camera_frame(
    u: int,
    v: int,
    depth_m: float,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> Tuple[float, float, float]:
    """
    Back-project pixel (u, v) with known metric depth to a 3-D point in the
    camera optical frame (Z forward, X right, Y down).

    Parameters
    ----------
    u, v    : pixel column and row
    depth_m : metric depth at (u, v) in metres
    fx, fy  : focal lengths in pixels
    cx, cy  : principal point in pixels

    Returns
    -------
    (X_c, Y_c, Z_c) in metres, in the camera optical frame.
    """
    x_c = (u - cx) * depth_m / fx
    y_c = (v - cy) * depth_m / fy
    z_c = depth_m
    return float(x_c), float(y_c), float(z_c)


# ── Stage 2: Camera frame → Robot base_link frame ────────────────────────────

def camera_to_robot_frame(
    x_c: float,
    y_c: float,
    z_c: float,
    camera_frame: str,
    robot_frame: str,
    tf_buffer: tf2_ros.Buffer,
) -> Optional[Tuple[float, float, float]]:
    """
    Transform a 3-D point from *camera_frame* to *robot_frame* via TF2, using
    the latest available transform rather than an exact past instant (see
    the comment below for why).

    Parameters
    ----------
    x_c, y_c, z_c : 3-D point in the camera optical frame (metres)
    camera_frame   : TF frame of the camera (e.g. 'camera_color_optical_frame')
    robot_frame    : TF frame of the robot base (e.g. 'base_link')
    tf_buffer      : live tf2_ros.Buffer

    Returns
    -------
    (X_r, Y_r, Z_r) in metres in *robot_frame*, or None if TF unavailable.
    """
    pt = PointStamped()
    pt.header.frame_id = camera_frame
    # Deliberately NOT using the image's own capture `stamp` here. An
    # exact-instant TF query has to win a race against this node's own TF
    # listener thread, which runs in the same process as (and can be
    # starved by) synchronous, CPU-bound YOLO inference in _image_cb --
    # confirmed live: robot-side TF was only ~1.4ms behind "now" at query
    # time, yet an exact-stamp lookup failed consistently, every time,
    # while a zero-stamp ("latest available") lookup succeeded 5/5.
    # This is also the more correct choice regardless: the strawberry is
    # stationary, so what matters is the robot's current reachable pose,
    # not its pose several hundred ms in the past when the photo was taken.
    pt.point.x = x_c
    pt.point.y = y_c
    pt.point.z = z_c

    try:
        transformed = tf_buffer.transform(
            pt,
            robot_frame,
            timeout=rclpy.duration.Duration(seconds=0.2),
        )
        return (
            float(transformed.point.x),
            float(transformed.point.y),
            float(transformed.point.z),
        )
    except Exception:
        return None


# ── Approach orientation from 2-D stem tilt ──────────────────────────────────

def stem_angle_to_quaternion(
    angle_deg: float,
) -> Tuple[float, float, float, float]:
    """
    Convert the 2-D stem tilt angle (degrees from vertical in image plane)
    to a gripper approach quaternion in the robot base frame.

    Convention
    ----------
    - angle_deg = 0   → stem is vertical → gripper points straight down
    - angle_deg ≠ 0   → apply additional rotation about the robot Z-axis
                        to align the gripper with the tilted stem axis.

    The gripper is expected to cut the peduncle by approaching along the
    stem axis from above (Figure 3, Xie 2024).

    Quaternion is for *link6* (the IK tip link), not the gripper case
    itself. The gripper is mounted on link6 via a fixed 90° rotation about
    X (see gripper_joint in piper_no_gripper_description.xacro), so
    "gripper Z points down" does NOT mean "rotate link6 180° about X" --
    that was tried and confirmed unreachable by /compute_ik at every
    tested position and radius (0.10m-0.47m), because it ignores that
    90° offset entirely. Solving for the link6 orientation that actually
    puts the *gripper's* Z axis straight down in world frame (accounting
    for the fixed link6->gripper rotation) and verifying the result is
    reachable via a live /compute_ik grid search over roll/yaw gives
    roll=90°, yaw=90° -- the clean quaternion (0.5, 0.5, 0.5, 0.5).
    Confirmed reachable at r=0.10m through 0.47m and at the real detected
    picking point, with and without the tilt rotation applied.

    Returns
    -------
    (qx, qy, qz, qw) – unit quaternion
    """
    from scipy.spatial.transform import Rotation as R

    # Base pose: puts the GRIPPER's (not link6's) Z axis straight down --
    # see docstring above for why this isn't a simple 180°-about-X on link6.
    r_base = R.from_euler("xz", [90.0, 90.0], degrees=True)

    # Tilt the approach around robot Z by the stem angle
    r_tilt = R.from_euler("z", float(angle_deg), degrees=True)

    r_final = r_tilt * r_base
    qx, qy, qz, qw = r_final.as_quat()  # scipy convention: (x,y,z,w)
    return float(qx), float(qy), float(qz), float(qw)
