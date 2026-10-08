#if !defined(COMMUNICATOR_HPP)
#define COMMUNICATOR_HPP

#include "vicon-datastream-sdk/DataStreamClient.h"
#include "rclcpp/rclcpp.hpp"
#include "publisher.hpp"
#include <iostream>
#include <map>
#include <chrono>
#include <string>
#include <unistd.h>
#include "boost/thread.hpp"
#include <set>

#include "geometry_msgs/msg/pose_stamped.hpp"
#include "geometry_msgs/msg/point_stamped.hpp"
#include "geometry_msgs/msg/transform_stamped.hpp"
#include "visualization_msgs/msg/marker.hpp"
#include "visualization_msgs/msg/marker_array.hpp"

#include "tf2/LinearMath/Quaternion.h"

#include "tf2_geometry_msgs/tf2_geometry_msgs.hpp"
#include "tf2_ros/transform_broadcaster.h"
#include "tf2_ros/static_transform_broadcaster.h"

#include "vicon_receiver/msg/marker_size.hpp"
#include "vicon_receiver/msg/marker_size_array.hpp"

#include <algorithm>
#include <vector>

using namespace std;

// Per-camera calibration needed to relate a 2D blob to a 3D marker.
// Only populated when EnableCameraCalibrationData() has been called: without it
// Nexus reports camera translations, focal lengths and principal points as
// failures (or zeros), which silently makes every size estimate zero/infinite.
struct CameraModel
{
    string name;
    double pos[3] = {0.0, 0.0, 0.0};   // camera position, Vicon global frame, mm
    double rot[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};  // row-major, camera -> world
    double f = 0.0;                    // focal length
    double cx = 0.0;                   // principal point x
    double cy = 0.0;                   // principal point y
    bool valid = false;
};


// Publisher class for PointStamped messages (for markers)
class PointPublisher
{
private:
    rclcpp::Publisher<geometry_msgs::msg::PointStamped>::SharedPtr point_publisher_;

public:
    bool is_ready = false;

    PointPublisher(std::string topic_name, rclcpp::Node* node)
    {
        point_publisher_ = node->create_publisher<geometry_msgs::msg::PointStamped>(topic_name, 10);
        is_ready = true;
    }

    void publish(geometry_msgs::msg::PointStamped point_msg)
    {
        point_publisher_->publish(point_msg);
    }
};

// Main Node class
class Communicator : public rclcpp::Node
{
private:
    ViconDataStreamSDK::CPP::Client vicon_client;

    string hostname;
    unsigned int buffer_size;
    string ns_name;

    // Publisher maps for segments (PoseStamped)
    map<string, Publisher> segment_pub_map;
    boost::mutex segment_mutex;
    std::set<std::string> pending_segment_publishers;

    // Publisher maps for labeled markers (PointStamped)
    map<string, PointPublisher> marker_pub_map;
    boost::mutex marker_mutex;
    std::set<std::string> pending_marker_publishers;

    // Publisher maps for unlabeled markers (PointStamped)
    map<unsigned int, PointPublisher> unlabeled_marker_pub_map;
    boost::mutex unlabeled_marker_mutex;
    std::set<unsigned int> pending_unlabeled_marker_publishers;

    // MarkerArray publishers for RViz2 visualization
    rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr labeled_markers_viz_pub_;
    rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr unlabeled_markers_viz_pub_;

    // PoC: per-camera 2D centroid data (radius + weight) for diameter inference
    rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr centroids_viz_pub_;
    bool centroid_weight_degenerate_reported = false;

    // Per-marker apparent size measurements (radius -> diameter)
    rclcpp::Publisher<vicon_receiver::msg::MarkerSizeArray>::SharedPtr marker_sizes_pub_;
    map<string, CameraModel> camera_models;
    // Number of camera models that were valid as of the last refresh; used to
    // warn once if calibration data is unavailable.
    bool calibration_warned = false;

    geometry_msgs::msg::TransformStamped static_tf;
    string world_frame;
    string vicon_frame;
    vector<double> map_xyz;
    vector<double> map_rpy;
    bool map_rpy_in_degrees;

    // Publish mode parameters
    bool publish_segments;
    bool publish_markers;
    bool publish_unlabeled_markers;
    bool publish_centroids;

    // Marker visualization parameters
    double marker_size;

    // Marker size measurement parameters
    bool publish_marker_sizes;
    double marker_diameter_scale;
    double marker_match_gate_px;

    std::shared_ptr<tf2_ros::StaticTransformBroadcaster> tf_static_broadcaster_;
    std::shared_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;

    void publish_static_transform();

    // Process segments data
    void process_segments();

    // Process labeled markers data
    void process_markers();

    // Process unlabeled markers data
    void process_unlabeled_markers();

    // Process per-camera centroid data (PoC: infer marker diameter)
    void process_centroids();

    // Refresh the cached per-camera calibration (position, rotation, intrinsics)
    void refresh_camera_models();

    // Publish per-marker apparent size measurements (radius -> diameter)
    void process_marker_sizes();

public:
    Communicator();

    // Initialises the connection to the DataStream server
    bool connect();

    // Stops the current connection to a DataStream server (if any).
    bool disconnect();

    // Main loop that request frames from the currently connected DataStream server and send the
    // received segment data to the Publisher class.
    void get_frame();

    // Functions to create a segment publisher in a new thread
    void create_segment_publisher(const string subject_name, const string segment_name);
    void create_segment_publisher_thread(const string subject_name, const string segment_name);

    // Functions to create a labeled marker publisher in a new thread
    void create_marker_publisher(const string subject_name, const string marker_name);
    void create_marker_publisher_thread(const string subject_name, const string marker_name);

    // Functions to create an unlabeled marker publisher in a new thread
    void create_unlabeled_marker_publisher(const unsigned int marker_index);
    void create_unlabeled_marker_publisher_thread(const unsigned int marker_index);
};

#endif // COMMUNICATOR_HPP