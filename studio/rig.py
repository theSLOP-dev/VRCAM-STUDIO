"""Camera rigs -> VRChat Camera Dolly paths.

A rig is up to 4 cameras placed around you (angle, distance, height). Each camera
becomes its own dolly *path*. With the dolly's Streaming setting on "Multi", VRChat
plays all paths at once and publishes one Spout sender per path - i.e. up to 4
simultaneous cameras, each recorded to its own file by this app.

Points are IsLocal=true, so the whole rig moves with you.
Dolly file format = flat JSON list of points (same as VRChat's own export).
"""
import json
import math
import os

PRESETS = {
    "front": {"angle": 0, "dist": 2.2, "height": 1.5},
    "3/4 left": {"angle": 40, "dist": 2.5, "height": 1.6},
    "3/4 right": {"angle": -40, "dist": 2.5, "height": 1.6},
    "profile left": {"angle": 90, "dist": 2.2, "height": 1.4},
    "behind": {"angle": 180, "dist": 2.5, "height": 1.8},
    "wide": {"angle": 20, "dist": 5.0, "height": 2.2},
    "overhead": {"angle": 0, "dist": 1.2, "height": 4.0},
    "low hero": {"angle": 15, "dist": 1.8, "height": 0.4},
}


def camera_point(cam, path_index, index, duration=60.0, look_height=1.2):
    """angle: 0 = in front of you, +90 = your left. Returns a dolly point dict."""
    a = math.radians(cam.get("angle", 0))
    d = float(cam.get("dist", 2.5))
    h = float(cam.get("height", 1.5))
    # player-local: +Z forward, +X right, +Y up. "your left" = -X.
    x, z = -math.sin(a) * d, math.cos(a) * d
    yaw = math.degrees(math.atan2(-x, -z))                 # face back toward you
    pitch = math.degrees(math.atan2(h - look_height, d))   # +X tilts down in Unity
    return {
        "Index": index, "PathIndex": path_index,
        "FocalDistance": max(0.0, min(10.0, d)), "Aperture": 15.0,
        "Hue": 120.0, "Saturation": 100.0, "Lightness": 50.0,
        "LookAtMeXOffset": 0.0, "LookAtMeYOffset": 0.0,
        "Zoom": float(cam.get("zoom", 45.0)), "Speed": 3.0, "Duration": duration,
        "Position": {"X": round(x, 3), "Y": round(h, 3), "Z": round(z, 3)},
        "Rotation": {"X": round(pitch, 2), "Y": round(yaw, 2), "Z": 0.0},
        "IsLocal": True,
    }


def build(cams):
    """Each camera = its own path with two identical points (a static shot)."""
    pts = []
    for p, cam in enumerate(cams[:4]):
        pts.append(camera_point(cam, p, 0))
        pts.append(camera_point(cam, p, 1))
    return pts


def paths_dir():
    return os.path.join(os.path.expanduser("~"), "Documents", "VRChat", "CameraPaths")


def write(cams, name="vrcam_rig"):
    os.makedirs(paths_dir(), exist_ok=True)
    fp = os.path.join(paths_dir(), f"{name}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(build(cams), f, indent=2)
    return fp
