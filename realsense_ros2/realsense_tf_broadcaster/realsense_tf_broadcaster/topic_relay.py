import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import CameraInfo, Image


MESSAGE_TYPES = {
    'image': Image,
    'camera_info': CameraInfo,
}


def _sensor_qos():
    return QoSProfile(
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=5,
    )


class TopicRelay(Node):
    def __init__(self):
        super().__init__('topic_relay')

        self.declare_parameter('input_topic', '')
        self.declare_parameter('output_topic', '')
        self.declare_parameter('message_type', 'image')

        input_topic = self.get_parameter('input_topic').value
        output_topic = self.get_parameter('output_topic').value
        message_type = self.get_parameter('message_type').value

        if not input_topic or not output_topic:
            raise ValueError('input_topic and output_topic must be set')

        msg_cls = MESSAGE_TYPES.get(str(message_type).lower())
        if msg_cls is None:
            raise ValueError(f'Unsupported message_type: {message_type}')

        qos = _sensor_qos()
        self._publisher = self.create_publisher(msg_cls, output_topic, qos)
        self._subscription = self.create_subscription(
            msg_cls,
            input_topic,
            self._publisher.publish,
            qos,
        )
        self.get_logger().info(
            f'Relaying {message_type} from {input_topic} to {output_topic}'
        )


def main(args=None):
    rclpy.init(args=args)
    node = TopicRelay()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
