"""
perception.launch.py
---------------------
Launches the strawberry_perception node with parameters loaded from
config/perception_params.yaml.

Usage:
    ros2 launch strawberry_perception perception.launch.py
    ros2 launch strawberry_perception perception.launch.py \
        det_weights:=/path/to/fruit.pt \
        seg_weights:=/path/to/stem.pt  \
        device:=cuda:0
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory("strawberry_perception")
    default_params = os.path.join(pkg_share, "config", "perception_params.yaml")

    return LaunchDescription([
        # Overridable launch arguments
        # Defaults match config/perception_params.yaml's trained weights, not
        # placeholder filenames -- these LaunchConfigurations get merged into
        # the Node's parameters *after* params_file, so whatever they resolve
        # to always overrides the YAML, even when left unspecified on the
        # command line. A placeholder default here silently defeated the
        # whole point of having a params_file: perception would run in
        # stub mode (zero detections) unless det_weights/seg_weights were
        # also re-passed on every single launch invocation.
        DeclareLaunchArgument(
            "det_weights",
            default_value=(
                "/home/soumo/Documents/HarvestBot/runs/detect/runs/detect/"
                "strawberry_yolov5s-6/weights/best.pt"
            ),
            description="Path to YOLOv5s fruit-detection weights (.pt)",
        ),
        DeclareLaunchArgument(
            "seg_weights",
            default_value=(
                "/home/soumo/Documents/HarvestBot/src/strawberry_perception/"
                "training/scripts/runs/segment/stem_yolov5s_seg-4/weights/best.pt"
            ),
            description="Path to YOLOv5s-seg stem-segmentation weights (.pt)",
        ),
        DeclareLaunchArgument(
            "device",
            default_value="cpu",
            description="Inference device: 'cpu' or 'cuda:0'",
        ),
        DeclareLaunchArgument(
            "params_file",
            default_value=default_params,
            description="Full path to the ROS parameters YAML file",
        ),
        DeclareLaunchArgument(
            "robot_frame",
            default_value="world",
            description=(
                "Target TF frame for the published pose/markers. Defaults to "
                "'world' (the robot's stable base frame) now that the full "
                "robot stack is the normal way this runs. NOT camera_link: "
                "the camera is wrist-mounted, so camera_link's orientation "
                "relative to world changes with every arm movement -- using "
                "it as the target frame means the message's axes mean a "
                "different real-world direction at every joint "
                "configuration. Override to robot_frame:=camera_link only "
                "for visual-only inspection with no robot_state_publisher "
                "running (world won't exist yet in that case)."
            ),
        ),

        Node(
            package="strawberry_perception",
            executable="detection_node",
            name="strawberry_perception",
            output="screen",
            parameters=[
                LaunchConfiguration("params_file"),
                {
                    # CLI overrides take precedence over the YAML file
                    "det_weights": LaunchConfiguration("det_weights"),
                    "seg_weights": LaunchConfiguration("seg_weights"),
                    "device":      LaunchConfiguration("device"),
                    "robot_frame": LaunchConfiguration("robot_frame"),
                },
            ],
        ),
    ])
