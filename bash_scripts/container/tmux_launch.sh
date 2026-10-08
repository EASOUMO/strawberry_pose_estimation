#!/bin/bash

SESSION="strawberry_perception"
WS_SETUP="source /opt/ros/jazzy/setup.bash && source ~/base_ws/install/setup.bash"

launch_window() {
    local name="$1"
    local cmd="$2"
    tmux new-window -t "$SESSION" -n "$name" bash -i
    sleep 2  # let .bashrc finish before typing
    tmux send-keys -t "$SESSION:$name" "$cmd" Enter
}

tmux has-session -t "$SESSION" 2>/dev/null && {
    echo "Session '$SESSION' already exists. Attach: tmux attach -t $SESSION"
    exit 0
}

tmux new-session -d -s "$SESSION" -n "realsense" bash -i
sleep 2  # let .bashrc finish before typing
tmux send-keys -t "realsense" "ros2 launch realsense2_camera rs_align_depth_launch.py" Enter
launch_window "perception" "ros2 launch strawberry_perception perception.launch.py robot_frame:=camera_link"
launch_window "rviz" "rviz2 -d ~/config/rvizconfig.rviz"
# launch_window "vicon" "ros2 launch vicon_receiver all.launch.py"

tmux select-window -t "$SESSION:1"
tmux attach -t "$SESSION"
