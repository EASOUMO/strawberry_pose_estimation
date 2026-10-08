FROM osrf/ros:jazzy-desktop-full

RUN apt-get update && apt-get install -y --no-install-recommends gnupg2 \
    && apt-key adv --keyserver keyserver.ubuntu.com --recv-keys F42ED6FBAB17C654

RUN echo "deb http://packages.ros.org/ros2-testing/ubuntu $(lsb_release -cs) main" \
    | tee /etc/apt/sources.list.d/ros2-testing.list

ARG  DEBIAN_FRONTEND=noninteractive
ARG  USERNAME=ubuntu

RUN apt-get update && apt-get install -y sudo git usbutils udev \
    && addgroup plugdev 2>/dev/null || true \
    && addgroup video 2>/dev/null || true \
    && addgroup dialout 2>/dev/null || true \
    && usermod -aG sudo ${USERNAME} \
    && usermod -aG plugdev ${USERNAME} \
    && usermod -aG video ${USERNAME} \
    && usermod -aG dialout ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers


ENV BASE_WS=/home/${USERNAME}/base_ws
RUN mkdir -p ${BASE_WS}/src \
    && chown -R ${USERNAME}:${USERNAME} ${BASE_WS}

ENV BASH_SCRIPTS=/home/${USERNAME}/bash_scripts
RUN mkdir -p ${BASH_SCRIPTS} \
    && chown -R ${USERNAME}:${USERNAME} ${BASH_SCRIPTS}

ENV ROSBAG_DIR=/home/${USERNAME}/rosbags
RUN mkdir -p ${ROSBAG_DIR} \
    && chown -R ${USERNAME}:${USERNAME} ${ROSBAG_DIR}

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    sudo git build-essential \
    gcc-12 g++-12 \
    python3 python3-pip \
    python3-colcon-common-extensions \
    python3-rosdep python3-rosdep-modules && \
    rm -rf /var/lib/apt/lists/*

ENV CC=/usr/bin/gcc-12
ENV CXX=/usr/bin/g++-12
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nvidia-cuda-toolkit && \
    rm -rf /var/lib/apt/lists/*

COPY docker/helper_math.h /usr/local/include/helper_math.h

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    vim nano htop tmux net-tools tree ffmpeg \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ros-jazzy-launch-testing \
    ros-jazzy-tf-transformations \
    ros-jazzy-launch-pytest \
    ros-jazzy-ament-cmake-core \
    ros-jazzy-rosbag2-storage-mcap \
    ros-jazzy-foxglove-bridge \
    libasio-dev \
    ros-jazzy-joy-linux \
    ros-jazzy-diagnostic-updater \
    ros-jazzy-image-transport \
    ros-jazzy-image-transport-plugins \
    ros-jazzy-cv-bridge \
    ros-jazzy-nav-msgs \
    ros-jazzy-tf2-ros \
    && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get purge -y ros-jazzy-librealsense2 2>/dev/null || true && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    iproute2 can-utils \
    libturbojpeg0-dev \
    libusb-1.0-0-dev \
    cmake \
    pkg-config && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libomp-dev \
    libpcap-dev \
    freeglut3-dev \
    libglfw3-dev \
    libxmu-dev \
    libxi-dev \
    ocl-icd-opencl-dev \
    opencl-headers \
    ocl-icd-libopencl1 \
    clinfo \
    python3-uvicorn \
    python3-fastapi \
    python3.12-venv && \
    rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/OpenKinect/libfreenect2.git
WORKDIR /libfreenect2/build
RUN cmake .. -DENABLE_CXX11=ON -DBUILD_OPENNI2_DRIVER=OFF -DENABLE_OPENCL=OFF -DENABLE_CUDA=ON -DENABLE_OPENGL=OFF -DENABLE_VAAPI=OFF -DENABLE_TEGRAJPEG=OFF -DCMAKE_INSTALL_PREFIX=/usr
RUN make
RUN make install

RUN git clone https://github.com/realsenseai/realsense-ros.git \
    -b 4.57.7 --depth 1 ${BASE_WS}/src/realsense-ros \
    && chown -R ${USERNAME}:${USERNAME} ${BASE_WS}/src/realsense-ros

COPY --from=rs_sdk lib /usr/local/lib
COPY --from=rs_sdk include /usr/local/include
COPY --from=rs_sdk share /usr/local/share

RUN rm -rf /usr/local/include/libfreenect2 /usr/local/lib/libfreenect2.so* \
 && ldconfig

COPY --chown=${USERNAME}:${USERNAME} realsense_ros2 ${BASE_WS}/src/realsense_ros2
COPY --chown=${USERNAME}:${USERNAME} vicon_ros      ${BASE_WS}/src/vicon_ros
COPY --chown=${USERNAME}:${USERNAME} strawberry_pose_estimation      ${BASE_WS}/src/strawberry_pose_estimation

RUN python3 -m pip install --no-cache-dir --break-system-packages \
    tmule==1.5.9 \
    pyserial

RUN mkdir -p /home/${USERNAME} && echo '{"context":{"dds":{"domain":0,"enabled":true}}}' \
    > /home/${USERNAME}/.realsense-config.json \
    && chown ${USERNAME}:${USERNAME} /home/${USERNAME}/.realsense-config.json

USER ${USERNAME}
WORKDIR /home/${USERNAME}

RUN sed -i 's/^#\(force_color_prompt\)/\1/' /home/${USERNAME}/.bashrc

RUN echo '[ -f $HOME/bash_scripts/bashrc_extensions.sh ] && \
    source $HOME/bash_scripts/bashrc_extensions.sh' \
    >> /home/${USERNAME}/.bashrc

COPY --chown=${USERNAME}:${USERNAME} bash_scripts/container/build_ws.sh ${BASH_SCRIPTS}/build_ws.sh

RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash \
    && CC=/usr/bin/gcc-13 CXX=/usr/bin/g++-13 ${BASH_SCRIPTS}/build_ws.sh"


# Strawberry perception runtime deps. Kept at the very bottom so this layer
# does not invalidate the (slow) colcon build above it.
#
# CPU-only PyTorch matches the node's default device: 'cpu' and avoids the
# ~2.5 GB CUDA wheels. For GPU inference (device: 'cuda:0' -- compose runs with
# `gpus: all`) switch the extra-index-url to
# https://download.pytorch.org/whl/cu124 and drop the '+cpu' local-version pins.
#
# setuptools is capped below 80: torch requires >=77.0.3, but setuptools 80
# removed the `setup.py develop --uninstall` option that `colcon build
# --symlink-install` (used by bash_scripts/container/build_ws.sh) relies on for
# ament_python packages -- without the cap, rebuilds fail with
# "error: option --uninstall not recognized".
RUN sudo python3 -m pip install --no-cache-dir --break-system-packages \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    "torch==2.14.1+cpu" "torchvision==0.29.1+cpu" "setuptools>=77,<80"

# ultralytics = YOLO inference.
#
# scipy is intentionally NOT installed: the base image already provides Debian
# scipy 1.11.4 (used for scipy.spatial.transform.Rotation in
# coordinate_transform.py), and pip cannot upgrade a Debian-managed package --
# it fails with "Cannot uninstall SciPy ... RECORD file not found".
#
# numpy is deliberately held at <2 for the same reason: numpy 1.26.4 in the
# base image is Debian-managed, so a numpy 2.x upgrade would fail identically.
# That also forces opencv-python to stay on 4.x (opencv-python 4.12+/5.x require
# numpy>=2); 4.11.0.86 is the newest 4.x that still accepts numpy 1.26.
RUN sudo python3 -m pip install --no-cache-dir --break-system-packages \
    "numpy<2" "opencv-python==4.11.0.86" "ultralytics==8.4.173"

# The pip setuptools above installs its own distutils-precedence.pth and
# _distutils_hack into /usr/local; the base image's Debian copy in /usr/lib is
# then a stale orphan that fails to import _distutils_hack on every Python
# startup ("Error processing line 1 of ... distutils-precedence.pth"). Remove
# it -- the shim is still provided by the /usr/local copy.
RUN sudo rm -f /usr/lib/python3/dist-packages/distutils-precedence.pth

CMD ["/bin/bash"]
