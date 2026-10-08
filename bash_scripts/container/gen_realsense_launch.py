#!/usr/bin/env python3
"""Generate ros2 run commands for RealSense cameras from realsense_config.yaml."""

import os
import sys
import tempfile

import yaml

CONFIG_PATH = os.path.join(
    os.environ.get("SENSOR_CONFIG_DIR", "/home/ubuntu/config"), "realsense_cameras.yaml"
)


def emit_camera_cmd(camera_name, cfg):
    serial = cfg["serial"]
    namespace = cfg.get("namespace", camera_name)

    # Write temp params file — serial must be a YAML string, not integer
    params_yaml = f"""/**:
  ros__parameters:
    serial_no: "{serial}"
    camera_name: "{namespace}"
    enable_color: true
    enable_depth: true
    enable_infra1: false
    enable_infra2: false
    enable_gyro: false
    enable_accel: false
    enable_motion: false
    enable_sync: false
    initial_reset: false
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="rs_cam_"
    ) as f:
        f.write(params_yaml)
        params_file = f.name

    # Remap camera topics to match what the D555 DDS bridge publishes
    remaps = [
        f"color/image_raw:=/realsense/D555_{serial}_Color",
        f"color/camera_info:=/realsense/D555_{serial}_Color/camera_info",
        f"depth/image_rect_raw:=/realsense/D555_{serial}_Depth",
        f"depth/camera_info:=/realsense/D555_{serial}_Depth/camera_info",
    ]

    cmd = "ros2 run realsense2_camera realsense2_camera_node --ros-args"
    cmd += f" -r __ns:=/realsense_{serial[-4:]}"
    for r in remaps:
        cmd += f" -r {r}"
    cmd += f" --params-file {params_file}"
    return cmd


def emit_tf_cmd(camera_name, cfg):
    frame = cfg.get("frame", f"{camera_name}_link")
    extra = cfg.get("extra_optical_frames", []) or []
    pos = cfg.get("position", {})
    ori = cfg.get("orientation", {})

    lines = []
    # map -> camera_link (calibrated)
    lines.append(
        f"ros2 run tf2_ros static_transform_publisher "
        f"--x {pos['x']} --y {pos['y']} --z {pos['z']} "
        f"--roll {ori['roll']} --pitch {ori['pitch']} --yaw {ori['yaw']} "
        f"--frame-id map --child-frame-id {frame}"
    )
    # camera_link -> optical frames (identity)
    for ef in extra:
        if ef:
            lines.append(
                f"ros2 run tf2_ros static_transform_publisher "
                f"--x 0 --y 0 --z 0 "
                f"--roll 0 --pitch 0 --yaw 0 "
                f"--frame-id {frame} --child-frame-id {ef}"
            )
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: gen_realsense_launch.py <cmd|tf>", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]

    if not os.path.exists(CONFIG_PATH):
        print(f"# config not found: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    cameras = config.get("cameras", {}) or {}

    for name, cfg in cameras.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", False):
            continue
        if not cfg.get("serial"):
            continue

        if mode == "cmd":
            print(emit_camera_cmd(name, cfg))
        elif mode == "tf":
            print(emit_tf_cmd(name, cfg))
        else:
            print(f"Unknown mode: {mode}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
