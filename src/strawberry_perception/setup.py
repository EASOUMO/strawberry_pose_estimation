from setuptools import find_packages, setup
import os
from glob import glob

package_name = "strawberry_perception"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        # ament resource index marker
        ("share/ament_index/resource_index/packages",
         [f"resource/{package_name}"]),
        # package.xml
        (f"share/{package_name}", ["package.xml"]),
        # launch files
        (os.path.join("share", package_name, "launch"),
         glob("launch/*.py")),
        # config files
        (os.path.join("share", package_name, "config"),
         glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="HarvestBot",
    maintainer_email="harvestbot@example.com",
    description="Strawberry perception: YOLOv5s detection + stem segmentation "
                "+ 3-D picking point localisation (Xie et al. 2024)",
    license="MIT",
    entry_points={
        "console_scripts": [
            # ros2 run strawberry_perception detection_node
            f"detection_node = {package_name}.detection_node:main",
        ],
    },
)
