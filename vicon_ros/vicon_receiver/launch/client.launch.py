from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():

    # Declare launch arguments
    hostname_arg = DeclareLaunchArgument(
        'hostname',
        default_value='192.168.10.1',
        description='Vicon server hostname or IP address'
    )
    buffer_size_arg = DeclareLaunchArgument(
        'buffer_size',
        default_value='200',
        description='Buffer size for Vicon data'
    )
    topic_namespace_arg = DeclareLaunchArgument(
        'topic_namespace',
        default_value='vicon',
        description='Topic namespace for Vicon messages'
    )
    world_frame_arg = DeclareLaunchArgument(
        'world_frame',
        default_value='map',
        description='World frame for the tf2 transformations'
    )
    vicon_frame_arg = DeclareLaunchArgument(
        'vicon_frame',
        default_value='vicon',
        description='Vicon frame for the tf2 transformations'
    )
    map_xyz_arg = DeclareLaunchArgument(
        'map_xyz',
        default_value='[0.0, 0.0, 0.0]',
        description='XYZ translation for coordinate frame mapping'
    )
    map_rpy_arg = DeclareLaunchArgument(
        'map_rpy',
        default_value='[0.0, 0.0, 0.0]',
        description='RPY rotation for coordinate frame mapping'
    )
    map_rpy_in_degrees_arg = DeclareLaunchArgument(
        'map_rpy_in_degrees',
        default_value='false',
        description='Whether RPY values are in degrees (true) or radians (false)'
    )

    # Publish mode arguments
    publish_segments_arg = DeclareLaunchArgument(
        'publish_segments',
        default_value='true',
        description='Enable publishing segment pose data (PoseStamped)'
    )
    publish_markers_arg = DeclareLaunchArgument(
        'publish_markers',
        default_value='false',
        description='Enable publishing labeled marker position data (PointStamped)'
    )
    publish_unlabeled_markers_arg = DeclareLaunchArgument(
        'publish_unlabeled_markers',
        default_value='false',
        description='Enable publishing unlabeled marker position data (PointStamped)'
    )

    # Marker visualization parameter
    marker_size_arg = DeclareLaunchArgument(
        'marker_size',
        default_value='0.02',
        description='Size of markers in RViz2 visualization (meters)'
    )

    # Get launch configuration values
    hostname = LaunchConfiguration('hostname')
    buffer_size = LaunchConfiguration('buffer_size')
    topic_namespace = LaunchConfiguration('topic_namespace')
    world_frame = LaunchConfiguration('world_frame')
    vicon_frame = LaunchConfiguration('vicon_frame')
    map_xyz = LaunchConfiguration('map_xyz')
    map_rpy = LaunchConfiguration('map_rpy')
    map_rpy_in_degrees = LaunchConfiguration('map_rpy_in_degrees')
    publish_segments = LaunchConfiguration('publish_segments')
    publish_markers = LaunchConfiguration('publish_markers')
    publish_unlabeled_markers = LaunchConfiguration('publish_unlabeled_markers')
    marker_size = LaunchConfiguration('marker_size')

    return LaunchDescription([
        # Launch arguments
        hostname_arg,
        buffer_size_arg,
        topic_namespace_arg,
        world_frame_arg,
        vicon_frame_arg,
        map_xyz_arg,
        map_rpy_arg,
        map_rpy_in_degrees_arg,
        publish_segments_arg,
        publish_markers_arg,
        publish_unlabeled_markers_arg,
        marker_size_arg,

        # Node
        Node(
            package='vicon_receiver',
            executable='vicon_client',
            output='screen',
            parameters=[{
                'hostname': hostname,
                'buffer_size': buffer_size,
                'namespace': topic_namespace,
                'world_frame': world_frame,
                'vicon_frame': vicon_frame,
                'map_xyz': map_xyz,
                'map_rpy': map_rpy,
                'map_rpy_in_degrees': map_rpy_in_degrees,
                'publish_segments': publish_segments,
                'publish_markers': publish_markers,
                'publish_unlabeled_markers': publish_unlabeled_markers,
                'marker_size': marker_size
            }]
        )
    ])
