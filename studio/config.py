"""Settings, loaded from settings.json next to the repo root (created on first run)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(ROOT, "settings.json")

DEFAULTS = {
    # where recordings go (one folder per session)
    "output_dir": os.path.join(os.path.expanduser("~"), "Videos", "VRCam Studio"),
    # web control page
    "web_host": "127.0.0.1",          # "0.0.0.0" to reach it from your phone on the LAN
    "web_port": 8480,
    "web_token": "",                  # required for non-localhost clients; generated on first run
    # recording
    "fps": 60,
    "encoder": "auto",                # auto | h264_nvenc | hevc_nvenc | h264_amf | h264_qsv | libx264
    "quality": 20,                    # CQ/QP-style quality, lower = better (18-26 sane)
    "segment_minutes": 5,             # files are split so a crash never loses more than this
    "always_on": False,               # start recording at launch and whenever a camera appears
    "record_audio": True,             # system audio (WASAPI loopback of the default output)
    "record_pov": False,              # also record your own screen (DXGI desktop capture)
    "pov_monitor": 0,
    "max_storage_gb": 0,              # >0: delete oldest sessions when the output folder exceeds this
    "sender_filter": "",              # only record Spout senders whose name contains this (empty = all)
    # VRChat OSC
    "osc_host": "127.0.0.1",
    "osc_send_port": 9000,
    "osc_listen_port": 9001,          # set 0 to disable listening (if another OSC app owns 9001)
    # Immich: upload each finished segment to your Immich server (empty url/key = off)
    "immich_url": "",                 # e.g. http://192.168.1.20:2283 (the address you open Immich at)
    "immich_api_key": "",             # Immich -> Account Settings -> API Keys
    "immich_album": "VRCam {session}",  # album per session; "" = no album; no {session} = one album
    "ffmpeg": "",                     # path to ffmpeg.exe; empty = tools/ffmpeg/bin/ffmpeg.exe or PATH
}


def load():
    s = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                s.update(json.load(f))
        except (OSError, ValueError) as e:
            print(f"[config] could not read settings.json ({e}); using defaults")
    if not s["web_token"]:
        import secrets
        s["web_token"] = secrets.token_urlsafe(9)
        save(s)
    elif not os.path.exists(SETTINGS_PATH):
        save(s)
    return s


def save(s):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
