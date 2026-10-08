#!/bin/bash

BASE_WS=${BASE_WS:-/home/ros/base_ws}
if [ ! -d "${BASE_WS}" ]; then
    echo "Error: BASE_WS directory '${BASE_WS}' not found. Exiting setup script."
    return 1
fi
cd "${BASE_WS}" || { echo "Error: Could not change to BASE_WS directory '${BASE_WS}'."; return 1; }
sudo ldconfig 2>/dev/null || true
export LD_LIBRARY_PATH="/usr/local/lib:$LD_LIBRARY_PATH"

if [ ! -f "install/setup.bash" ] || [ "$1" == "--rebuild" ]; then
    if [ -d "build" ] || [ -d "install" ]; then
        echo "Cleaning previous build artifacts..."
        rm -rf build install log
        echo "Cleaned."
    fi

    echo "Running colcon build..."
    if ! bash "$HOME/bash_scripts/build_ws.sh"; then
        echo "Error: colcon build failed! Please check the build output above."
        echo "To retry, run: wbuild --rebuild"
    fi
else
    echo "Workspace already built (install/setup.bash found). Skipping colcon build."
    echo "To force a rebuild, run 'wbuild --rebuild'."
fi

REALSENSE_CONFIG="$HOME/.realsense-config.json"
if [ ! -f "$REALSENSE_CONFIG" ]; then
    echo 'Creating RealSense DDS config...'
    cat > "$REALSENSE_CONFIG" << 'REALEOF'
{
  "context": {
    "dds": {
      "domain": 0,
      "enabled": true
    }
  }
}
REALEOF
fi
echo "Sourcing ROS 2 base environment..."
source /opt/ros/jazzy/setup.bash
echo "Sourcing workspace environment..."
source ${BASE_WS}/install/setup.bash

echo "ROS 2 workspace setup and sourced. Happy robot wrangling!"
alias launch_vicon="ros2 launch vicon_receiver all.launch.py"
alias calibrate_cameras="ros2 run kinect2_bridge vicon_marker_calibration_tf.py"

alias start="ros2 service call /start_recording std_srvs/srv/Trigger"
alias stop="ros2 service call /stop_recording std_srvs/srv/Trigger"

alias launch_all="bash $HOME/bash_scripts/tmux_launch.sh"
alias terminate_all="bash $HOME/bash_scripts/tmux_terminate.sh"


alias refresh_usb="bash $HOME/bash_scripts/refresh_usb.sh"
alias wclean="rm -rf ${BASE_WS}/build ${BASE_WS}/install ${BASE_WS}/log && echo 'Workspace cleaned.'"
alias wbuild="bash $HOME/bash_scripts/build_ws.sh --clean && source ${BASE_WS}/install/setup.bash"

export _ROS_WORKSPACE_SETUP_RUN=true
