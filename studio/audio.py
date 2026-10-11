"""System audio (everything you hear in VRChat) via WASAPI loopback -> segmented AAC."""
import os
import subprocess
import threading
import time

from . import ffmpeg

RATE = 48000
BLOCK = 1024


class AudioRecorder(threading.Thread):
    def __init__(self, session):
        super().__init__(daemon=True)
        self.session = session
        self.stop_evt = threading.Event()
        self.err = ""
        self.started = None
        self.level = 0.0

    def run(self):
        s = self.session
        try:
            import soundcard as sc
            import numpy as np
            spk = sc.default_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
        except Exception as e:
            self.err = f"audio unavailable: {e}"
            s.log(self.err)
            return
        folder = os.path.join(s.dir, "audio")
        os.makedirs(folder, exist_ok=True)
        pattern = os.path.join(folder, f"audio_{time.strftime('%H%M%S')}_%03d.m4a")
        args = [s.ff, "-hide_banner", "-loglevel", "error",
                "-f", "f32le", "-ar", str(RATE), "-ac", "2", "-i", "-",
                "-c:a", "aac", "-b:a", "192k",
                "-f", "segment", "-segment_time", str(int(s.segment_minutes * 60)), "-reset_timestamps", "1",
                "-segment_format", "mp4", pattern]
        p = subprocess.Popen(args, stdin=subprocess.PIPE, creationflags=ffmpeg.CREATE_NO_WINDOW)
        s.log(f"[audio] recording '{spk.name}' (loopback)")
        try:
            with mic.recorder(samplerate=RATE, channels=2, blocksize=BLOCK) as rec:
                self.started = time.time()
                s.mark_file("audio", pattern, 0, 0)
                while not self.stop_evt.is_set():
                    data = rec.record(numframes=BLOCK)
                    if data.ndim == 1:
                        data = np.repeat(data[:, None], 2, axis=1)
                    self.level = float(abs(data).max()) if data.size else 0.0
                    p.stdin.write(data[:, :2].astype("float32").tobytes())
        except Exception as e:
            self.err = f"audio error: {e}"
            s.log(self.err)
        finally:
            try:
                p.stdin.close()
                p.wait(timeout=20)
            except Exception:
                p.kill()

    def stop(self):
        self.stop_evt.set()


class PovRecorder:
    """Optional: your own screen (what you see), via DXGI desktop duplication in ffmpeg."""

    def __init__(self, session, monitor=0):
        self.session = session
        self.monitor = monitor
        self.proc = None

    def start(self):
        s = self.session
        folder = os.path.join(s.dir, "pov")
        os.makedirs(folder, exist_ok=True)
        pattern = os.path.join(folder, f"pov_{time.strftime('%H%M%S')}_%03d.mp4")
        src = f"ddagrab=output_idx={self.monitor}:framerate={s.fps},hwdownload,format=bgra"
        args = [s.ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src,
                "-pix_fmt", "yuv420p"] + ffmpeg.video_args(s.encoder, s.quality) + \
            ffmpeg.segment_args(s.segment_minutes, pattern)
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, creationflags=ffmpeg.CREATE_NO_WINDOW)
        s.mark_file("pov", pattern, 0, 0)
        s.log(f"[pov] recording monitor {self.monitor}")

    def stop(self):
        if self.proc:
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
                self.proc.wait(timeout=20)
            except Exception:
                self.proc.kill()
            self.proc = None
