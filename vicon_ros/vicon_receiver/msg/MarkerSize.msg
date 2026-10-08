# Apparent size measurement for a single Vicon marker.
#
# The radius comes from the 2D centroid of the marker's blob in a camera image.
# It is an APPARENT size: the blob is a thresholded retroreflective return, so it
# does not exactly match the physical marker silhouette, and it varies with
# exposure, viewing angle and occlusion.
#
# Fields are -1.0 when the value could not be determined.

string  name           # "Subject/Marker" for labeled, "marker_<index>" for unlabeled

bool    labeled        # true if the marker belongs to a subject

uint32  camera_count   # cameras that contributed a usable blob (0 = none)

float64 radius_px      # median blob radius across contributing cameras
float64 distance_mm    # median camera-to-marker distance across those cameras

# Derived apparent diameter: scale * 2 * radius_px * distance_mm / focal_length.
# 'scale' is the marker_diameter_scale parameter; leave it at 1.0 until you have
# fitted it against markers of known physical diameter.
float64 diameter_mm
