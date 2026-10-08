from setuptools import find_packages, setup

package_name = "realsense_tf_broadcaster"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=("test",)),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (
            f"share/{package_name}/launch",
            [
                "launch/realsense_poe_relay.launch.py",
                "launch/realsense_multi_camera.launch.py",
            ],
        ),
        (f"share/{package_name}/rviz", ["rviz/realsense_map.rviz"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="oali",
    maintainer_email="oali@example.com",
    description="Publish static map-frame transforms for configured RealSense cameras.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "topic_relay = realsense_tf_broadcaster.topic_relay:main",
        ],
    },
)
