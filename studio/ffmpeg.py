"""Locate ffmpeg and pick the best working hardware encoder."""
import os
import shutil
import subprocess

from .config import ROOT

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# tried in order; first one that can actually encode a test frame wins
CANDIDATES = ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"]


def find(settings):
    if settings.get("ffmpeg") and os.path.exists(settings["ffmpeg"]):
        return settings["ffmpeg"]
    local = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if os.path.exists(local):
        return local
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("ffmpeg not found - run install.bat (it downloads ffmpeg into tools/ffmpeg)")


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, **kw)


def works(ff, enc):
    r = run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=30",
             "-frames:v", "3", "-c:v", enc, "-f", "null", "-"], timeout=20)
    return r.returncode == 0


def pick_encoder(ff, wanted="auto"):
    if wanted and wanted != "auto":
        return wanted
    for enc in CANDIDATES:
        try:
            if works(ff, enc):
                return enc
        except Exception:
            continue
    return "libx264"


def video_args(enc, quality):
    """Encoder flags tuned for continuous recording (low latency, constant quality)."""
    q = str(int(quality))
    if enc.endswith("_nvenc"):
        return ["-c:v", enc, "-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", q, "-b:v", "0"]
    if enc.endswith("_amf"):
        return ["-c:v", enc, "-quality", "balanced", "-rc", "cqp", "-qp_i", q, "-qp_p", q]
    if enc.endswith("_qsv"):
        return ["-c:v", enc, "-preset", "medium", "-global_quality", q]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", q]


def segment_args(minutes, pattern):
    """Write crash-safe chunks: each segment is a complete, playable mp4."""
    return ["-f", "segment", "-segment_time", str(int(minutes * 60)), "-reset_timestamps", "1",
            "-segment_format", "mp4", "-segment_format_options", "movflags=+faststart",
            "-strftime", "0", pattern]
