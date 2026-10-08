import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/soumo/strawberry_pose_estimation/install/strawberry_perception'
