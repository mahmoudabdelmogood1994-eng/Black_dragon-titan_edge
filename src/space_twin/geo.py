"""Small geodesy helpers (local tangent-plane approximation, < 50 km)."""
import math
import numpy as np

M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON_EQ = 111320.0


def to_enu(lat, lon, lat0, lon0):
    """lat/lon -> (east_m, north_m) relative to (lat0, lon0)."""
    return ((np.asarray(lon) - lon0) * M_PER_DEG_LON_EQ * math.cos(math.radians(lat0)),
            (np.asarray(lat) - lat0) * M_PER_DEG_LAT)


def to_latlon(e, n, lat0, lon0):
    return (lat0 + np.asarray(n) / M_PER_DEG_LAT,
            lon0 + np.asarray(e) / (M_PER_DEG_LON_EQ * math.cos(math.radians(lat0))))


def dist_km(lat1, lon1, lat2, lon2):
    e, n = to_enu(lat2, lon2, lat1, lon1)
    return float(math.hypot(e, n)) / 1000.0
