import os

import yaml

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _default_config_path():
    base_ws = os.environ.get('BASE_WS', '/home/ubuntu/base_ws')
    return os.path.join(base_ws, 'src', 'realsense_ros2', 'realsense_config.yaml')


def _launch_setup(context, *args, **kwargs):
    config_file = LaunchConfiguration('config_file').perform(context)

    if not os.path.exists(config_file):
        return [LogInfo(msg=f'Config file not found: {config_file}')]

    with open(config_file, 'r', encoding='utf-8') as handle:
        config = yaml.safe_load(handle) or {}

    world_frame = config.get('world_frame', 'map')
    cameras = config.get('cameras', {}) or {}

    actions = [LogInfo(msg=f'Loading PoE camera relays from {config_file}')]

    for camera_name, camera_config in cameras.items():
        if not isinstance(camera_config, dict):
            continue
        if not camera_config.get('enabled', False):
            continue

        namespace = camera_config.get('namespace', camera_name)
        source_color = camera_config.get('source_color_topic')
        source_color_info = camera_config.get('source_color_info_topic')
        output_image = camera_config.get('output_image_topic')
        output_info = camera_config.get('output_info_topic')

        if not source_color or not source_color_info:
            actions.append(LogInfo(msg=f'Skipping {camera_name}: missing source topics'))
            continue

        output_image = output_image or f'/{namespace}/image'
        output_info = output_info or f'/{namespace}/camera_info'

        if output_image != source_color:
            actions.append(
                Node(
                    package='realsense_tf_broadcaster',
                    executable='topic_relay',
                    name=f'{camera_name}_image_relay',
                    output='screen',
                    parameters=[{
                        'input_topic': source_color,
                        'output_topic': output_image,
                        'message_type': 'image',
                    }],
                )
            )

        if output_info != source_color_info:
            actions.append(
                Node(
                    package='realsense_tf_broadcaster',
                    executable='topic_relay',
                    name=f'{camera_name}_camera_info_relay',
                    output='screen',
                    parameters=[{
                        'input_topic': source_color_info,
                        'output_topic': output_info,
                        'message_type': 'camera_info',
                    }],
                )
            )

    for camera_name, camera_config in cameras.items():
        if not isinstance(camera_config, dict):
            continue
        if not camera_config.get('enabled', False):
            continue

        position = camera_config.get('position', {}) or {}
        orientation = camera_config.get('orientation', {}) or {}
        child_frame = camera_config.get('frame', f'{camera_name}_link')
        optical_frame = camera_config.get('optical_frame')
        extra_frames = camera_config.get('extra_optical_frames', []) or []

        required_position = ('x', 'y', 'z')
        required_orientation = ('roll', 'pitch', 'yaw')
        if any(axis not in position for axis in required_position):
            actions.append(LogInfo(msg=f'Skipping {camera_name}: missing position values'))
            continue
        if any(axis not in orientation for axis in required_orientation):
            actions.append(LogInfo(msg=f'Skipping {camera_name}: missing orientation values'))
            continue

        frames_to_publish = [child_frame]
        if optical_frame:
            frames_to_publish.append(optical_frame)
        for frame_name in extra_frames:
            if frame_name and frame_name not in frames_to_publish:
                frames_to_publish.append(frame_name)

        for frame_name in frames_to_publish:
            actions.append(
                Node(
                    package='tf2_ros',
                    executable='static_transform_publisher',
                    name=f'{camera_name}_{frame_name}_static_tf',
                    output='screen',
                    arguments=[
                        '--x', str(float(position['x'])),
                        '--y', str(float(position['y'])),
                        '--z', str(float(position['z'])),
                        '--yaw', str(float(orientation['yaw'])),
                        '--pitch', str(float(orientation['pitch'])),
                        '--roll', str(float(orientation['roll'])),
                        '--frame-id', world_frame,
                        '--child-frame-id', frame_name,
                    ],
                )
            )

    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=_default_config_path(),
            description='Path to realsense_config.yaml',
        ),
        OpaqueFunction(function=_launch_setup),
    ])
