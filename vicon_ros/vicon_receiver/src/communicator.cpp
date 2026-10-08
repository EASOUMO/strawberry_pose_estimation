#include "vicon_receiver/communicator.hpp"

#include <cmath>
#include <iomanip>
#include <sstream>

using namespace ViconDataStreamSDK::CPP;

// Constructor for the Communicator class
Communicator::Communicator() : Node("vicon_client")
{
    // Declare parameters for hostname, buffer size, and namespace
    this->declare_parameter<std::string>("hostname", "127.0.0.1");
    this->declare_parameter<int>("buffer_size", 200);
    this->declare_parameter<std::string>("namespace", "vicon");
    this->declare_parameter<std::string>("world_frame", "map");
    this->declare_parameter<std::string>("vicon_frame", "vicon");
    this->declare_parameter<std::vector<double>>("map_xyz",  {0.0, 0.0, 0.0});
    this->declare_parameter<std::vector<double>>("map_rpy",  {0.0, 0.0, 0.0});
    this->declare_parameter<bool>("map_rpy_in_degrees", false);
    
    // Declare parameters for publish modes
    this->declare_parameter<bool>("publish_segments", true);
    this->declare_parameter<bool>("publish_markers", false);
    this->declare_parameter<bool>("publish_unlabeled_markers", false);
    
    // Declare parameter for marker visualization size (in meters)
    this->declare_parameter<double>("marker_size", 0.02);

    // PoC: publish per-camera 2D centroid data (radius + weight)
    this->declare_parameter<bool>("publish_centroids", true);

    // Per-marker apparent size measurement
    this->declare_parameter<bool>("publish_marker_sizes", true);
    // Multiply the raw 2*radius*distance/f estimate by this to correct the
    // systematic blob-vs-silhouette bias; fit it against known markers.
    this->declare_parameter<double>("marker_diameter_scale", 1.0);
    // Projected-to-observed blob matching gate for unlabeled markers, pixels.
    this->declare_parameter<double>("marker_match_gate_px", 150.0);

    // Retrieve parameters values
    this->get_parameter("hostname", hostname);
    this->get_parameter("buffer_size", buffer_size);
    this->get_parameter("namespace", ns_name);

    this->get_parameter("world_frame", world_frame);
    this->get_parameter("vicon_frame", vicon_frame);
    this->get_parameter("map_xyz", map_xyz);
    this->get_parameter("map_rpy", map_rpy);
    this->get_parameter("map_rpy_in_degrees", map_rpy_in_degrees);
    
    // Retrieve publish mode parameters
    this->get_parameter("publish_segments", publish_segments);
    this->get_parameter("publish_markers", publish_markers);
    this->get_parameter("publish_unlabeled_markers", publish_unlabeled_markers);
    
    // Retrieve marker visualization size
    this->get_parameter("marker_size", marker_size);
    this->get_parameter("publish_centroids", publish_centroids);
    this->get_parameter("publish_marker_sizes", publish_marker_sizes);
    this->get_parameter("marker_diameter_scale", marker_diameter_scale);
    this->get_parameter("marker_match_gate_px", marker_match_gate_px);

    // Publish static transform from map to vicon origin
    if (map_rpy_in_degrees) {
        for (unsigned int i=0; i<map_rpy.size(); i++) {
            map_rpy[i] = map_rpy[i] * M_PI / 180.0;
        }
    }
    tf_static_broadcaster_ = std::make_shared<tf2_ros::StaticTransformBroadcaster>(this);
    this->publish_static_transform();

    // Initialize the tf2 broadcaster
    tf_broadcaster_ = std::make_shared<tf2_ros::TransformBroadcaster>(this);
    
    // Create MarkerArray publishers for RViz2 visualization
    if (publish_markers) {
        labeled_markers_viz_pub_ = this->create_publisher<visualization_msgs::msg::MarkerArray>(
            ns_name + "/markers_visualization", 10);
        cout << "Created MarkerArray publisher for labeled markers visualization" << endl;
    }
    
    if (publish_unlabeled_markers) {
        unlabeled_markers_viz_pub_ = this->create_publisher<visualization_msgs::msg::MarkerArray>(
            ns_name + "/unlabeled_markers_visualization", 10);
        cout << "Created MarkerArray publisher for unlabeled markers visualization" << endl;
    }

    if (publish_centroids) {
        centroids_viz_pub_ = this->create_publisher<visualization_msgs::msg::MarkerArray>(
            ns_name + "/centroids_visualization", 10);
        cout << "Created MarkerArray publisher for per-camera centroid data (PoC)" << endl;
    }

    if (publish_marker_sizes) {
        marker_sizes_pub_ = this->create_publisher<vicon_receiver::msg::MarkerSizeArray>(
            ns_name + "/marker_sizes", 10);
        cout << "Created publisher for per-marker size measurements" << endl;
    }
    
    // Log publish modes
    cout << "Publish modes - Segments: " << (publish_segments ? "ON" : "OFF")
         << ", Markers: " << (publish_markers ? "ON" : "OFF")
         << ", Unlabeled Markers: " << (publish_unlabeled_markers ? "ON" : "OFF")
         << ", Centroids: " << (publish_centroids ? "ON" : "OFF")
         << ", Marker sizes: " << (publish_marker_sizes ? "ON" : "OFF") << endl;
    cout << "Marker visualization size: " << marker_size << " meters" << endl;
}

// Publish the static transform from map to vicon origin
void Communicator::publish_static_transform()
{
    static_tf.header.stamp = this->get_clock()->now();
    static_tf.header.frame_id = world_frame;
    static_tf.child_frame_id = vicon_frame;

    static_tf.transform.translation.x = map_xyz[0];
    static_tf.transform.translation.y = map_xyz[1];
    static_tf.transform.translation.z = map_xyz[2];
    tf2::Quaternion q;
    q.setRPY(
        map_rpy[0],
        map_rpy[1],
        map_rpy[2]
    );
    static_tf.transform.rotation.x = q.x();
    static_tf.transform.rotation.y = q.y();
    static_tf.transform.rotation.z = q.z();
    static_tf.transform.rotation.w = q.w();

    tf_static_broadcaster_->sendTransform(static_tf);

    string msg = "Published static transform from " + world_frame + " to " + vicon_frame;
    cout << msg << endl;
}


// Connect to the Vicon server
bool Communicator::connect()
{
    // Log connection attempt
    string msg = "Connecting to " + hostname + " ...";
    cout << msg << endl;

    int counter = 0;
    // Retry connection until successful
    while (!vicon_client.IsConnected().Connected && rclcpp::ok())
    {
        bool ok = (vicon_client.Connect(hostname).Result == Result::Success);
        if (!ok)
        {
            counter++;
            msg = "Connect failed, reconnecting (" + std::to_string(counter) + ")...";
            cout << msg << endl;
        }
    }
    if (!rclcpp::ok()) {
        std::cout << "Shutdown requested before connection established." << std::endl;
        return false;
    }

    // Log successful connection
    msg = "Connection successfully established with " + hostname;
    cout << msg << endl;

    // Enable various data streams from the Vicon server
    vicon_client.EnableSegmentData();
    vicon_client.EnableMarkerData();
    vicon_client.EnableUnlabeledMarkerData();
    vicon_client.EnableMarkerRayData();
    vicon_client.EnableDeviceData();
    vicon_client.EnableDebugData();

    // PoC: 2D centroid data carries the per-blob radius and the centroid weight
    Output_EnableCentroidData centroid_enable = vicon_client.EnableCentroidData();
    cout << "EnableCentroidData: "
         << (centroid_enable.Result == Result::Success ? "Success" : "FAILED") << endl;

    // Required for GetCameraGlobalTranslation/Rotation and the camera intrinsics.
    // Without it those calls fail (or return zeros) and every marker size
    // estimate would come out as zero or infinite.
    Output_EnableCameraCalibrationData calibration_enable = vicon_client.EnableCameraCalibrationData();
    cout << "EnableCameraCalibrationData: "
         << (calibration_enable.Result == Result::Success ? "Success" : "FAILED") << endl;

    // Set the stream mode and buffer size
    vicon_client.SetStreamMode(StreamMode::ClientPull);
    vicon_client.SetBufferSize(buffer_size);

    // Log initialization completion
    msg = "Initialization complete";
    cout << msg << endl;

    return true;
}

// Disconnect from the Vicon server
bool Communicator::disconnect()
{
    // If already disconnected, return true
    if (!vicon_client.IsConnected().Connected)
        return true;

    sleep(1); // Wait before disconnecting

    // Disable all data streams
    vicon_client.DisableSegmentData();
    vicon_client.DisableMarkerData();
    vicon_client.DisableUnlabeledMarkerData();
    vicon_client.DisableDeviceData();
    vicon_client.DisableCentroidData();

    // Log disconnection attempt
    string msg = "Disconnecting from " + hostname + "...";
    cout << msg << endl;

    // Disconnect from the server
    vicon_client.Disconnect();

    // Log successful disconnection
    msg = "Successfully disconnected";
    cout << msg << endl;

    // Verify disconnection
    return !vicon_client.IsConnected().Connected;
}

// Retrieve and process a frame of data from the Vicon server
void Communicator::get_frame()
{
    // Request a new frame
    vicon_client.GetFrame();
    Output_GetFrameNumber frame_number = vicon_client.GetFrameNumber();

    // Process data based on publish modes
    if (publish_segments) {
        process_segments();
    }
    
    if (publish_markers) {
        process_markers();
    }
    
    if (publish_unlabeled_markers) {
        process_unlabeled_markers();
    }

    if (publish_centroids) {
        process_centroids();
    }

    if (publish_marker_sizes) {
        process_marker_sizes();
    }
}

// Process segment data from Vicon server
void Communicator::process_segments()
{
    // Get the number of subjects in the frame
    unsigned int subject_count = vicon_client.GetSubjectCount().SubjectCount;

    map<string, Publisher>::iterator pub_it;

    // Iterate through each subject
    for (unsigned int subject_index = 0; subject_index < subject_count; ++subject_index)
    {
        // Get the subject name
        string subject_name = vicon_client.GetSubjectName(subject_index).SubjectName;

        // Get the number of segments for the subject
        unsigned int segment_count = vicon_client.GetSegmentCount(subject_name).SegmentCount;

        // Iterate through each segment
        for (unsigned int segment_index = 0; segment_index < segment_count; ++segment_index)
        {
            // Get the segment name
            string segment_name = vicon_client.GetSegmentName(subject_name, segment_index).SegmentName;

            // Retrieve the segment's global position and rotation
            Output_GetSegmentGlobalTranslation trans =
                vicon_client.GetSegmentGlobalTranslation(subject_name, segment_name);
            Output_GetSegmentGlobalRotationQuaternion quat =
                vicon_client.GetSegmentGlobalRotationQuaternion(subject_name, segment_name);

            // Skip occluded segments (markers not visible to Vicon cameras)
            if (trans.Occluded || quat.Occluded)
            {
                continue;
            }

            // Build a TF message for this segment
            geometry_msgs::msg::TransformStamped tf_msg;

            // Use node clock to timestamp the transform
            tf_msg.header.stamp = this->get_clock()->now();

            // Parent and child frames: Vicon global origin -> subject_segment
            tf_msg.header.frame_id = vicon_frame;
            tf_msg.child_frame_id = subject_name + "_" + segment_name;

            // Vicon translations are in millimeters; convert to meters for ROS
            tf_msg.transform.translation.x = trans.Translation[0] / 1000.0;
            tf_msg.transform.translation.y = trans.Translation[1] / 1000.0;
            tf_msg.transform.translation.z = trans.Translation[2] / 1000.0;

            // Vicon quaternion order is [x, y, z, w]; copy directly
            tf_msg.transform.rotation.x = quat.Rotation[0];
            tf_msg.transform.rotation.y = quat.Rotation[1];
            tf_msg.transform.rotation.z = quat.Rotation[2];
            tf_msg.transform.rotation.w = quat.Rotation[3];

            // Publish the position data
            boost::mutex::scoped_try_lock lock(segment_mutex);
            if (lock.owns_lock())
            {
                // Check if a publisher exists for the segment
                pub_it = segment_pub_map.find(subject_name + "/" + segment_name);
                if (pub_it != segment_pub_map.end())
                {
                    Publisher & pub = pub_it->second;

                    if (pub.is_ready)
                    {
                        // Build a PoseStamped in the Vicon frame from the computed TransformStamped.
                        geometry_msgs::msg::PoseStamped vicon_pose_msg;

                        // Header: copy timestamp and frame_id ("vicon") from the transform header.
                        vicon_pose_msg.header = tf_msg.header;

                        // Position: copy the already meter-converted translation components.
                        vicon_pose_msg.pose.position.x = tf_msg.transform.translation.x;
                        vicon_pose_msg.pose.position.y = tf_msg.transform.translation.y;
                        vicon_pose_msg.pose.position.z = tf_msg.transform.translation.z;

                        // Orientation: copy the quaternion (x, y, z, w) directly from the transform.
                        vicon_pose_msg.pose.orientation = tf_msg.transform.rotation;

                        // Update timestamp of static transform
                        static_tf.header.stamp = tf_msg.header.stamp;

                        // Transform the pose to the global frame
                        geometry_msgs::msg::PoseStamped global_pose_msg;
                        tf2::doTransform(vicon_pose_msg, global_pose_msg, static_tf);

                        // Publish the transformed pose
                        pub.publish(global_pose_msg);
                    }
                }
                else
                {
                    // Create a publisher if it doesn't exist, de-duplicating concurrent attempts
                    std::string key = subject_name + "/" + segment_name;
                    if (pending_segment_publishers.find(key) == pending_segment_publishers.end())
                    {
                        pending_segment_publishers.insert(key);
                        lock.unlock();
                        create_segment_publisher(subject_name, segment_name);
                    }
                    else
                    {
                        // Another thread is already creating this publisher
                        lock.unlock();
                    }
                }
            }

            // Broadcast the transform
            tf_broadcaster_->sendTransform(tf_msg);
        }
    }
}

// Process labeled marker data from Vicon server
void Communicator::process_markers()
{
    // Get the number of subjects in the frame
    unsigned int subject_count = vicon_client.GetSubjectCount().SubjectCount;

    map<string, PointPublisher>::iterator pub_it;
    
    // Create MarkerArray for visualization
    visualization_msgs::msg::MarkerArray marker_array;
    int marker_id = 0;
    auto now = this->get_clock()->now();

    // Iterate through each subject
    for (unsigned int subject_index = 0; subject_index < subject_count; ++subject_index)
    {
        // Get the subject name
        string subject_name = vicon_client.GetSubjectName(subject_index).SubjectName;

        // Get the number of markers for the subject
        unsigned int marker_count = vicon_client.GetMarkerCount(subject_name).MarkerCount;

        // Iterate through each marker
        for (unsigned int marker_index = 0; marker_index < marker_count; ++marker_index)
        {
            // Get the marker name
            string marker_name = vicon_client.GetMarkerName(subject_name, marker_index).MarkerName;

            // Retrieve the marker's global position
            Output_GetMarkerGlobalTranslation trans =
                vicon_client.GetMarkerGlobalTranslation(subject_name, marker_name);

            // Skip occluded markers
            if (trans.Occluded)
            {
                continue;
            }

            // Convert position from mm to meters
            double x = trans.Translation[0] / 1000.0;
            double y = trans.Translation[1] / 1000.0;
            double z = trans.Translation[2] / 1000.0;

            // Build a TF message for this marker
            geometry_msgs::msg::TransformStamped tf_msg;
            tf_msg.header.stamp = now;
            tf_msg.header.frame_id = vicon_frame;
            tf_msg.child_frame_id = subject_name + "_marker_" + marker_name;

            tf_msg.transform.translation.x = x;
            tf_msg.transform.translation.y = y;
            tf_msg.transform.translation.z = z;

            // Markers don't have rotation, use identity quaternion
            tf_msg.transform.rotation.x = 0.0;
            tf_msg.transform.rotation.y = 0.0;
            tf_msg.transform.rotation.z = 0.0;
            tf_msg.transform.rotation.w = 1.0;
            
            // Add sphere marker for visualization
            visualization_msgs::msg::Marker sphere_marker;
            sphere_marker.header.frame_id = vicon_frame;
            sphere_marker.header.stamp = now;
            sphere_marker.ns = subject_name;
            sphere_marker.id = marker_id;
            sphere_marker.type = visualization_msgs::msg::Marker::SPHERE;
            sphere_marker.action = visualization_msgs::msg::Marker::ADD;
            sphere_marker.pose.position.x = x;
            sphere_marker.pose.position.y = y;
            sphere_marker.pose.position.z = z;
            sphere_marker.pose.orientation.w = 1.0;
            sphere_marker.scale.x = marker_size;
            sphere_marker.scale.y = marker_size;
            sphere_marker.scale.z = marker_size;
            // Green color for labeled markers
            sphere_marker.color.r = 0.0f;
            sphere_marker.color.g = 1.0f;
            sphere_marker.color.b = 0.0f;
            sphere_marker.color.a = 1.0f;
            sphere_marker.lifetime = rclcpp::Duration::from_seconds(0.1);
            marker_array.markers.push_back(sphere_marker);
            
            // Add text marker for the label
            visualization_msgs::msg::Marker text_marker;
            text_marker.header.frame_id = vicon_frame;
            text_marker.header.stamp = now;
            text_marker.ns = subject_name + "_labels";
            text_marker.id = marker_id;
            text_marker.type = visualization_msgs::msg::Marker::TEXT_VIEW_FACING;
            text_marker.action = visualization_msgs::msg::Marker::ADD;
            text_marker.pose.position.x = x;
            text_marker.pose.position.y = y;
            text_marker.pose.position.z = z + marker_size + 0.01; // Slightly above the sphere
            text_marker.pose.orientation.w = 1.0;
            text_marker.scale.z = marker_size * 1.5; // Text height
            text_marker.color.r = 1.0f;
            text_marker.color.g = 1.0f;
            text_marker.color.b = 1.0f;
            text_marker.color.a = 1.0f;
            text_marker.text = marker_name;
            text_marker.lifetime = rclcpp::Duration::from_seconds(0.1);
            marker_array.markers.push_back(text_marker);
            
            marker_id++;

            // Publish the position data to individual topics
            boost::mutex::scoped_try_lock lock(marker_mutex);
            if (lock.owns_lock())
            {
                // Check if a publisher exists for the marker
                pub_it = marker_pub_map.find(subject_name + "/" + marker_name);
                if (pub_it != marker_pub_map.end())
                {
                    PointPublisher & pub = pub_it->second;

                    if (pub.is_ready)
                    {
                        // Build a PointStamped in the Vicon frame
                        geometry_msgs::msg::PointStamped vicon_point_msg;
                        vicon_point_msg.header.stamp = now;
                        vicon_point_msg.header.frame_id = vicon_frame;

                        vicon_point_msg.point.x = x;
                        vicon_point_msg.point.y = y;
                        vicon_point_msg.point.z = z;

                        // Update timestamp of static transform
                        static_tf.header.stamp = now;

                        // Transform the point to the global frame
                        geometry_msgs::msg::PointStamped global_point_msg;
                        tf2::doTransform(vicon_point_msg, global_point_msg, static_tf);

                        // Publish the transformed point
                        pub.publish(global_point_msg);
                    }
                }
                else
                {
                    // Create a publisher if it doesn't exist, de-duplicating concurrent attempts
                    std::string key = subject_name + "/" + marker_name;
                    if (pending_marker_publishers.find(key) == pending_marker_publishers.end())
                    {
                        pending_marker_publishers.insert(key);
                        lock.unlock();
                        create_marker_publisher(subject_name, marker_name);
                    }
                    else
                    {
                        // Another thread is already creating this publisher
                        lock.unlock();
                    }
                }
            }

            // Broadcast the transform
            tf_broadcaster_->sendTransform(tf_msg);
        }
    }
    
    // Publish the MarkerArray for visualization
    if (!marker_array.markers.empty() && labeled_markers_viz_pub_) {
        labeled_markers_viz_pub_->publish(marker_array);
    }
}

// Process unlabeled marker data from Vicon server
void Communicator::process_unlabeled_markers()
{
    // Get the number of unlabeled markers
    unsigned int unlabeled_marker_count = vicon_client.GetUnlabeledMarkerCount().MarkerCount;

    map<unsigned int, PointPublisher>::iterator pub_it;
    
    // Create MarkerArray for visualization
    visualization_msgs::msg::MarkerArray marker_array;
    auto now = this->get_clock()->now();

    // Iterate through each unlabeled marker
    for (unsigned int marker_index = 0; marker_index < unlabeled_marker_count; ++marker_index)
    {
        // Retrieve the unlabeled marker's global position
        Output_GetUnlabeledMarkerGlobalTranslation trans =
            vicon_client.GetUnlabeledMarkerGlobalTranslation(marker_index);

        // Convert position from mm to meters
        double x = trans.Translation[0] / 1000.0;
        double y = trans.Translation[1] / 1000.0;
        double z = trans.Translation[2] / 1000.0;

        // Build a TF message for this unlabeled marker
        geometry_msgs::msg::TransformStamped tf_msg;
        tf_msg.header.stamp = now;
        tf_msg.header.frame_id = vicon_frame;
        tf_msg.child_frame_id = "unlabeled_marker_" + std::to_string(marker_index);

        tf_msg.transform.translation.x = x;
        tf_msg.transform.translation.y = y;
        tf_msg.transform.translation.z = z;

        // Markers don't have rotation, use identity quaternion
        tf_msg.transform.rotation.x = 0.0;
        tf_msg.transform.rotation.y = 0.0;
        tf_msg.transform.rotation.z = 0.0;
        tf_msg.transform.rotation.w = 1.0;
        
        // Add sphere marker for visualization
        visualization_msgs::msg::Marker sphere_marker;
        sphere_marker.header.frame_id = vicon_frame;
        sphere_marker.header.stamp = now;
        sphere_marker.ns = "unlabeled";
        sphere_marker.id = marker_index;
        sphere_marker.type = visualization_msgs::msg::Marker::SPHERE;
        sphere_marker.action = visualization_msgs::msg::Marker::ADD;
        sphere_marker.pose.position.x = x;
        sphere_marker.pose.position.y = y;
        sphere_marker.pose.position.z = z;
        sphere_marker.pose.orientation.w = 1.0;
        sphere_marker.scale.x = marker_size;
        sphere_marker.scale.y = marker_size;
        sphere_marker.scale.z = marker_size;
        // Orange color for unlabeled markers
        sphere_marker.color.r = 1.0f;
        sphere_marker.color.g = 0.5f;
        sphere_marker.color.b = 0.0f;
        sphere_marker.color.a = 1.0f;
        sphere_marker.lifetime = rclcpp::Duration::from_seconds(0.1);
        marker_array.markers.push_back(sphere_marker);
        
        // Add text marker for the index label
        visualization_msgs::msg::Marker text_marker;
        text_marker.header.frame_id = vicon_frame;
        text_marker.header.stamp = now;
        text_marker.ns = "unlabeled_labels";
        text_marker.id = marker_index;
        text_marker.type = visualization_msgs::msg::Marker::TEXT_VIEW_FACING;
        text_marker.action = visualization_msgs::msg::Marker::ADD;
        text_marker.pose.position.x = x;
        text_marker.pose.position.y = y;
        text_marker.pose.position.z = z + marker_size + 0.01; // Slightly above the sphere
        text_marker.pose.orientation.w = 1.0;
        text_marker.scale.z = marker_size * 1.5; // Text height
        text_marker.color.r = 1.0f;
        text_marker.color.g = 1.0f;
        text_marker.color.b = 1.0f;
        text_marker.color.a = 1.0f;
        text_marker.text = "unlabeled_" + std::to_string(marker_index);
        text_marker.lifetime = rclcpp::Duration::from_seconds(0.1);
        marker_array.markers.push_back(text_marker);

        // Publish the position data to individual topics
        boost::mutex::scoped_try_lock lock(unlabeled_marker_mutex);
        if (lock.owns_lock())
        {
            // Check if a publisher exists for this unlabeled marker
            pub_it = unlabeled_marker_pub_map.find(marker_index);
            if (pub_it != unlabeled_marker_pub_map.end())
            {
                PointPublisher & pub = pub_it->second;

                if (pub.is_ready)
                {
                    // Build a PointStamped in the Vicon frame
                    geometry_msgs::msg::PointStamped vicon_point_msg;
                    vicon_point_msg.header.stamp = now;
                    vicon_point_msg.header.frame_id = vicon_frame;

                    vicon_point_msg.point.x = x;
                    vicon_point_msg.point.y = y;
                    vicon_point_msg.point.z = z;

                    // Update timestamp of static transform
                    static_tf.header.stamp = now;

                    // Transform the point to the global frame
                    geometry_msgs::msg::PointStamped global_point_msg;
                    tf2::doTransform(vicon_point_msg, global_point_msg, static_tf);

                    // Publish the transformed point
                    pub.publish(global_point_msg);
                }
            }
            else
            {
                // Create a publisher if it doesn't exist, de-duplicating concurrent attempts
                if (pending_unlabeled_marker_publishers.find(marker_index) == pending_unlabeled_marker_publishers.end())
                {
                    pending_unlabeled_marker_publishers.insert(marker_index);
                    lock.unlock();
                    create_unlabeled_marker_publisher(marker_index);
                }
                else
                {
                    // Another thread is already creating this publisher
                    lock.unlock();
                }
            }
        }

        // Broadcast the transform
        tf_broadcaster_->sendTransform(tf_msg);
    }
    
    // Publish the MarkerArray for visualization
    if (!marker_array.markers.empty() && unlabeled_markers_viz_pub_) {
        unlabeled_markers_viz_pub_->publish(marker_array);
    }
}

// PoC: publish the per-camera 2D centroid data so it can be checked whether the
// marker diameter can be inferred from the centroid weight.
//
// The working hypothesis is that Output_GetCentroidWeight.Weight holds the
// volume of the blob, in which case a sphere of volume W has diameter
//     d = 2 * cbrt(3W / 4pi)
// Output_GetCentroidPosition.Radius gives the blob radius directly, so
//     d = 2 * Radius
// is published alongside it for comparison.
//
// IMPORTANT: the SDK documents the weight as a centroid weight and states that
// it is "Only supported by Tracker - weights will be 1.0 for all centroids if
// Low Jitter mode is not enabled". On a Nexus server it may therefore carry no
// size information at all; this function detects that case and says so.
//
// The published numbers are RAW and unconverted. Neither the units of Radius nor
// of Weight are documented by Vicon ("position and radius of the centroid in
// camera coordinates"), so this only shows whether the quantity tracks marker
// size, not what the diameter is in millimetres.
void Communicator::process_centroids()
{
    const unsigned int camera_count = vicon_client.GetCameraCount().CameraCount;
    if (camera_count == 0)
    {
        return;
    }

    visualization_msgs::msg::MarkerArray marker_array;
    auto now = this->get_clock()->now();

    // Keep the debug view bounded: centroids are per camera, so an 8+ camera
    // system can easily produce thousands of blobs per frame.
    const unsigned int max_markers = 400;
    bool truncated = false;

    unsigned int centroid_total = 0;
    unsigned int weights_at_one = 0;
    int marker_id = 0;

    // Arbitrary panel spacing so each camera's image plane is laid out apart.
    // The centroid coordinates are in undocumented camera units, not metres.
    const double camera_panel_spacing = 200.0;

    for (unsigned int camera_index = 0; camera_index < camera_count; ++camera_index)
    {
        const string camera_name = vicon_client.GetCameraName(camera_index).CameraName;
        const unsigned int centroid_count =
            vicon_client.GetCentroidCount(camera_name).CentroidCount;

        for (unsigned int centroid_index = 0; centroid_index < centroid_count; ++centroid_index)
        {
            Output_GetCentroidPosition pos =
                vicon_client.GetCentroidPosition(camera_name, centroid_index);
            if (pos.Result != Result::Success)
            {
                continue;
            }

            Output_GetCentroidWeight weight =
                vicon_client.GetCentroidWeight(camera_name, centroid_index);

            const double radius = pos.Radius;
            const double w = (weight.Result == Result::Success) ? weight.Weight : -1.0;

            // Hypothesis under test: Weight is the blob volume (sphere)
            const double diameter_from_weight =
                (w > 0.0) ? 2.0 * std::cbrt(3.0 * w / (4.0 * M_PI)) : -1.0;
            const double diameter_from_radius = (radius > 0.0) ? 2.0 * radius : -1.0;

            centroid_total++;
            if (w == 1.0)
            {
                weights_at_one++;
            }

            if (marker_id >= static_cast<int>(max_markers))
            {
                truncated = true;
                continue;
            }

            // NOTE: centroid coordinates are camera-plane coordinates, not world
            // coordinates. They are published in vicon_frame only so RViz can
            // display them as a debug view, one panel per camera.
            const double u = pos.CentroidPosition[0];
            const double v = pos.CentroidPosition[1];
            const double panel_z = camera_index * camera_panel_spacing;

            // A distinct colour per camera makes the panels distinguishable
            const float shade = static_cast<float>((camera_index * 67) % 200 + 55) / 255.0f;

            visualization_msgs::msg::Marker sphere;
            sphere.header.frame_id = vicon_frame;
            sphere.header.stamp = now;
            sphere.ns = camera_name;
            sphere.id = marker_id;
            sphere.type = visualization_msgs::msg::Marker::SPHERE;
            sphere.action = visualization_msgs::msg::Marker::ADD;
            sphere.pose.position.x = u;
            sphere.pose.position.y = v;
            sphere.pose.position.z = panel_z;
            sphere.pose.orientation.w = 1.0;
            // Sphere scale is the diameter; draw the weight-derived value that is
            // under test, falling back to marker_size when it is unusable
            const double draw_size = (diameter_from_weight > 0.0) ? diameter_from_weight : marker_size;
            sphere.scale.x = draw_size;
            sphere.scale.y = draw_size;
            sphere.scale.z = draw_size;
            sphere.color.r = shade;
            sphere.color.g = 1.0f - shade;
            sphere.color.b = 1.0f;
            sphere.color.a = 1.0f;
            sphere.lifetime = rclcpp::Duration::from_seconds(0.1);
            marker_array.markers.push_back(sphere);

            std::ostringstream label;
            label << std::fixed << std::setprecision(2)
                  << camera_name << " #" << centroid_index
                  << " R=" << radius
                  << " W=" << w
                  << " dR=" << diameter_from_radius
                  << " dW=" << diameter_from_weight;

            visualization_msgs::msg::Marker text;
            text.header.frame_id = vicon_frame;
            text.header.stamp = now;
            text.ns = camera_name + "_labels";
            text.id = marker_id;
            text.type = visualization_msgs::msg::Marker::TEXT_VIEW_FACING;
            text.action = visualization_msgs::msg::Marker::ADD;
            text.pose.position.x = u;
            text.pose.position.y = v;
            text.pose.position.z = panel_z + draw_size;
            text.pose.orientation.w = 1.0;
            text.scale.z = marker_size;
            text.color.r = 1.0f;
            text.color.g = 1.0f;
            text.color.b = 1.0f;
            text.color.a = 1.0f;
            text.text = label.str();
            text.lifetime = rclcpp::Duration::from_seconds(0.1);
            marker_array.markers.push_back(text);

            marker_id++;
        }
    }

    // A constant weight of 1.0 for every centroid means the server is not
    // supplying per-centroid weights at all, so nothing can be inferred from them.
    if (centroid_total > 0 && weights_at_one == centroid_total && !centroid_weight_degenerate_reported)
    {
        cout << "WARNING: GetCentroidWeight returned 1.0 for all " << centroid_total
             << " centroids. The SDK documents this field as Tracker-only, so on this server it"
             << " carries no size information. Compare the dR (radius) column instead." << endl;
        centroid_weight_degenerate_reported = true;
    }

    if (truncated)
    {
        cout << "Centroid debug view truncated at " << max_markers << " markers ("
             << centroid_total << " centroids present)" << endl;
    }

    if (!marker_array.markers.empty() && centroids_viz_pub_)
    {
        centroids_viz_pub_->publish(marker_array);
    }
}

// Median of a copy of the given values; -1.0 when empty.
static double median_of(std::vector<double> values)
{
    if (values.empty())
    {
        return -1.0;
    }
    std::sort(values.begin(), values.end());
    const size_t n = values.size();
    return (n % 2 == 1) ? values[n / 2] : 0.5 * (values[n / 2 - 1] + values[n / 2]);
}

// Project a point in the Vicon global frame (mm) through a camera model.
// CameraModel::rot is row-major and maps camera -> world, so the world -> camera
// transform is its transpose. Returns false when the point is behind the camera.
// This axis/sign convention was validated against the SDK's own marker-ray
// ground truth (mean reprojection error ~61 px on an 18x Vero v2.2 system).
static bool project_point(const CameraModel & model, const double point[3],
                          double & u, double & v)
{
    const double dx = point[0] - model.pos[0];
    const double dy = point[1] - model.pos[1];
    const double dz = point[2] - model.pos[2];

    const double xc = model.rot[0] * dx + model.rot[3] * dy + model.rot[6] * dz;
    const double yc = model.rot[1] * dx + model.rot[4] * dy + model.rot[7] * dz;
    const double zc = model.rot[2] * dx + model.rot[5] * dy + model.rot[8] * dz;
    if (zc <= 1e-6)
    {
        return false;
    }

    u = model.f * xc / zc + model.cx;
    v = model.f * yc / zc + model.cy;
    return true;
}

// Refresh the cached per-camera calibration. Camera position, rotation and
// intrinsics are only reported once EnableCameraCalibrationData() has been
// called, and even then they can be absent for the first frames, so entries that
// are not usable yet are marked invalid and retried on the next frame rather
// than being cached as zeros.
void Communicator::refresh_camera_models()
{
    const unsigned int camera_count = vicon_client.GetCameraCount().CameraCount;
    unsigned int valid_count = 0;

    for (unsigned int i = 0; i < camera_count; ++i)
    {
        const string camera_name = vicon_client.GetCameraName(i).CameraName;
        CameraModel & model = camera_models[camera_name];
        model.name = camera_name;

        Output_GetCameraFocalLength focal = vicon_client.GetCameraFocalLength(camera_name);
        Output_GetCameraPrincipalPoint principal =
            vicon_client.GetCameraPrincipalPoint(camera_name);
        Output_GetCameraGlobalTranslation translation =
            vicon_client.GetCameraGlobalTranslation(camera_name);
        Output_GetCameraGlobalRotationMatrix rotation =
            vicon_client.GetCameraGlobalRotationMatrix(camera_name);

        if (focal.Result != Result::Success || focal.FocalLength <= 0.0 ||
            principal.Result != Result::Success ||
            translation.Result != Result::Success ||
            rotation.Result != Result::Success)
        {
            model.valid = false;
            continue;
        }

        for (int k = 0; k < 3; ++k)
        {
            model.pos[k] = translation.Translation[k];
        }
        for (int k = 0; k < 9; ++k)
        {
            model.rot[k] = rotation.Rotation[k];
        }
        model.f = focal.FocalLength;
        model.cx = principal.PrincipalPointX;
        model.cy = principal.PrincipalPointY;
        model.valid = true;
        valid_count++;
    }

    if (valid_count == 0 && camera_count > 0 && !calibration_warned)
    {
        cout << "WARNING: " << camera_count << " cameras are visible but none report usable"
             << " calibration data. Check that EnableCameraCalibrationData() succeeded;"
             << " without it camera poses and intrinsics are unavailable." << endl;
        calibration_warned = true;
    }
}

// Publish the per-marker apparent size measurement.
//
// The radius comes from the 2D blob centroid, so a physical size needs three
// things: the blob radius, the camera-to-marker distance, and the camera focal
// length. All three are only available with camera calibration data enabled.
//
//   diameter = scale * 2 * radius * distance / f
//
// Labeled markers are matched exactly: the SDK links a named marker to the
// centroid indices that produced it (GetMarkerRayContribution). Unlabeled
// markers have no such link, so their 3D position is projected into each camera
// and matched to the nearest blob within marker_match_gate_px. That match is
// approximate - see the reprojection error noted on project_point().
void Communicator::process_marker_sizes()
{
    refresh_camera_models();

    vicon_receiver::msg::MarkerSizeArray out;
    out.header.stamp = this->get_clock()->now();
    out.header.frame_id = vicon_frame;

    // Resolve a ray contribution's CameraID back to a camera name.
    map<unsigned int, string> camera_id_to_name;
    for (map<string, CameraModel>::const_iterator it = camera_models.begin();
         it != camera_models.end(); ++it)
    {
        if (!it->second.valid)
        {
            continue;
        }
        camera_id_to_name[vicon_client.GetCameraId(it->first).CameraId] = it->first;
    }

    // --- Labeled markers: exact blob association via the marker's rays. ---
    const unsigned int subject_count = vicon_client.GetSubjectCount().SubjectCount;
    for (unsigned int subject_index = 0; subject_index < subject_count; ++subject_index)
    {
        const string subject_name = vicon_client.GetSubjectName(subject_index).SubjectName;
        const unsigned int marker_count = vicon_client.GetMarkerCount(subject_name).MarkerCount;

        for (unsigned int marker_index = 0; marker_index < marker_count; ++marker_index)
        {
            const string marker_name =
                vicon_client.GetMarkerName(subject_name, marker_index).MarkerName;
            const unsigned int ray_count =
                vicon_client.GetMarkerRayContributionCount(subject_name, marker_name)
                    .RayContributionsCount;
            if (ray_count == 0)
            {
                continue;
            }

            Output_GetMarkerGlobalTranslation position =
                vicon_client.GetMarkerGlobalTranslation(subject_name, marker_name);
            if (position.Result != Result::Success)
            {
                continue;
            }

            vector<double> radii;
            vector<double> distances;
            vector<double> diameters;

            for (unsigned int ray = 0; ray < ray_count; ++ray)
            {
                Output_GetMarkerRayContribution contribution =
                    vicon_client.GetMarkerRayContribution(subject_name, marker_name, ray);
                map<unsigned int, string>::const_iterator camera =
                    camera_id_to_name.find(contribution.CameraID);
                if (camera == camera_id_to_name.end())
                {
                    continue;
                }

                const CameraModel & model = camera_models[camera->second];
                Output_GetCentroidPosition blob =
                    vicon_client.GetCentroidPosition(camera->second, contribution.CentroidIndex);
                if (blob.Result != Result::Success || blob.Radius <= 0.0)
                {
                    continue;
                }

                const double dx = position.Translation[0] - model.pos[0];
                const double dy = position.Translation[1] - model.pos[1];
                const double dz = position.Translation[2] - model.pos[2];
                const double distance = std::sqrt(dx * dx + dy * dy + dz * dz);
                if (distance <= 0.0 || model.f <= 0.0)
                {
                    continue;
                }

                radii.push_back(blob.Radius);
                distances.push_back(distance);
                diameters.push_back(marker_diameter_scale * 2.0 * blob.Radius * distance / model.f);
            }

            if (radii.empty())
            {
                continue;
            }

            vicon_receiver::msg::MarkerSize entry;
            entry.name = subject_name + "/" + marker_name;
            entry.labeled = true;
            entry.camera_count = static_cast<unsigned int>(radii.size());
            entry.radius_px = median_of(radii);
            entry.distance_mm = median_of(distances);
            entry.diameter_mm = median_of(diameters);
            out.markers.push_back(entry);
        }
    }

    // --- Unlabeled markers: no SDK link, so project and match the nearest blob. ---
    unsigned int unlabeled_seen = 0;
    unsigned int unlabeled_matched = 0;
    double residual_sum = 0.0;

    const unsigned int unlabeled_count = vicon_client.GetUnlabeledMarkerCount().MarkerCount;
    for (unsigned int marker_index = 0; marker_index < unlabeled_count; ++marker_index)
    {
        Output_GetUnlabeledMarkerGlobalTranslation position =
            vicon_client.GetUnlabeledMarkerGlobalTranslation(marker_index);
        if (position.Result != Result::Success)
        {
            continue;
        }
        unlabeled_seen++;

        vector<double> radii;
        vector<double> distances;
        vector<double> diameters;

        for (map<string, CameraModel>::const_iterator it = camera_models.begin();
             it != camera_models.end(); ++it)
        {
            const CameraModel & model = it->second;
            if (!model.valid || model.f <= 0.0)
            {
                continue;
            }

            double u = 0.0;
            double v = 0.0;
            if (!project_point(model, position.Translation, u, v))
            {
                continue;
            }

            const double dx = position.Translation[0] - model.pos[0];
            const double dy = position.Translation[1] - model.pos[1];
            const double dz = position.Translation[2] - model.pos[2];
            const double distance = std::sqrt(dx * dx + dy * dy + dz * dz);

            const unsigned int centroid_count =
                vicon_client.GetCentroidCount(model.name).CentroidCount;
            double best_residual = marker_match_gate_px;
            double best_radius = -1.0;

            for (unsigned int centroid_index = 0; centroid_index < centroid_count; ++centroid_index)
            {
                Output_GetCentroidPosition blob =
                    vicon_client.GetCentroidPosition(model.name, centroid_index);
                if (blob.Result != Result::Success)
                {
                    continue;
                }
                const double residual = std::hypot(
                    blob.CentroidPosition[0] - u, blob.CentroidPosition[1] - v);
                if (residual < best_residual)
                {
                    best_residual = residual;
                    best_radius = blob.Radius;
                }
            }

            if (best_radius <= 0.0)
            {
                continue;
            }

            radii.push_back(best_radius);
            distances.push_back(distance);
            diameters.push_back(marker_diameter_scale * 2.0 * best_radius * distance / model.f);
            residual_sum += best_residual;
        }

        if (radii.empty())
        {
            continue;
        }
        unlabeled_matched++;

        vicon_receiver::msg::MarkerSize entry;
        // NOTE: unlabeled indices are not stable frame to frame, so this name
        // identifies a position in this frame only.
        entry.name = "marker_" + std::to_string(marker_index);
        entry.labeled = false;
        entry.camera_count = static_cast<unsigned int>(radii.size());
        entry.radius_px = median_of(radii);
        entry.distance_mm = median_of(distances);
        entry.diameter_mm = median_of(diameters);
        out.markers.push_back(entry);
    }

    // One-shot diagnostic so the projection gate can be judged from the log.
    static bool reported = false;
    if (!reported && !out.markers.empty())
    {
        cout << "Marker size measurements: " << out.markers.size() << " markers,"
             << " " << camera_id_to_name.size() << " calibrated cameras";
        if (unlabeled_seen > 0)
        {
            cout << "; unlabeled " << unlabeled_matched << "/" << unlabeled_seen << " matched"
                 << ", mean match residual "
                 << (unlabeled_matched > 0 ? residual_sum / unlabeled_matched : 0.0) << " px"
                 << " (gate " << marker_match_gate_px << " px)";
        }
        cout << endl;
        reported = true;
    }

    if (marker_sizes_pub_)
    {
        marker_sizes_pub_->publish(out);
    }
}

// Create a publisher for a specific subject and segment
void Communicator::create_segment_publisher(const string subject_name, const string segment_name)
{
    // Launch a thread to create the publisher
    boost::thread(&Communicator::create_segment_publisher_thread, this, subject_name, segment_name);
}

// Thread function to create a segment publisher
void Communicator::create_segment_publisher_thread(const string subject_name, const string segment_name)
{
    // Construct the topic name and key
    std::string topic_name = ns_name + "/segments/" + subject_name + "/" + segment_name;
    std::string key = subject_name + "/" + segment_name;

    // Log publisher creation
    string msg = "Creating publisher for segment " + segment_name + " from subject " + subject_name;
    cout << msg << endl;

    // Create and store the publisher; then clear the pending flag
    boost::mutex::scoped_lock lock(segment_mutex);
    segment_pub_map.insert(std::map<std::string, Publisher>::value_type(key, Publisher(topic_name, this)));
    pending_segment_publishers.erase(key);
    lock.unlock();
}

// Create a publisher for a specific subject and marker
void Communicator::create_marker_publisher(const string subject_name, const string marker_name)
{
    // Launch a thread to create the publisher
    boost::thread(&Communicator::create_marker_publisher_thread, this, subject_name, marker_name);
}

// Thread function to create a marker publisher
void Communicator::create_marker_publisher_thread(const string subject_name, const string marker_name)
{
    // Construct the topic name and key
    std::string topic_name = ns_name + "/markers/" + subject_name + "/" + marker_name;
    std::string key = subject_name + "/" + marker_name;

    // Log publisher creation
    string msg = "Creating publisher for marker " + marker_name + " from subject " + subject_name;
    cout << msg << endl;

    // Create and store the publisher; then clear the pending flag
    boost::mutex::scoped_lock lock(marker_mutex);
    marker_pub_map.insert(std::map<std::string, PointPublisher>::value_type(key, PointPublisher(topic_name, this)));
    pending_marker_publishers.erase(key);
    lock.unlock();
}

// Create a publisher for an unlabeled marker
void Communicator::create_unlabeled_marker_publisher(const unsigned int marker_index)
{
    // Launch a thread to create the publisher
    boost::thread(&Communicator::create_unlabeled_marker_publisher_thread, this, marker_index);
}

// Thread function to create an unlabeled marker publisher
void Communicator::create_unlabeled_marker_publisher_thread(const unsigned int marker_index)
{
    // Construct the topic name (prefix with 'marker_' to avoid starting with a number)
    std::string topic_name = ns_name + "/unlabeled_markers/marker_" + std::to_string(marker_index);

    // Log publisher creation
    string msg = "Creating publisher for unlabeled marker " + std::to_string(marker_index);
    cout << msg << endl;

    // Create and store the publisher; then clear the pending flag
    boost::mutex::scoped_lock lock(unlabeled_marker_mutex);
    unlabeled_marker_pub_map.insert(std::map<unsigned int, PointPublisher>::value_type(marker_index, PointPublisher(topic_name, this)));
    pending_unlabeled_marker_publishers.erase(marker_index);
    lock.unlock();
}

// Main function
int main(int argc, char** argv)
{
    // Initialize the ROS 2 node
    rclcpp::init(argc, argv);
    auto node = std::make_shared<Communicator>();

    // Connect to the Vicon server
    node->connect();

    // Continuously retrieve frames while ROS 2 is running
    while (rclcpp::ok()){
        node->get_frame();
    }

    // Disconnect from the Vicon server and shut down ROS 2
    node->disconnect();
    rclcpp::shutdown();
    return 0;
}