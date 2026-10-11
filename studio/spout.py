"""Spout receivers: one thread per VRChat camera sender, each piping frames into ffmpeg.

VRChat's Stream Camera (and each extra Camera Dolly "Multi" stream camera) publishes a
Spout sender. Spout shares the camera's GPU texture directly, so recording never
touches what you see on your own screen / headset.
"""
import array
import os
import subprocess
import threading
import time

from . import audio, ffmpeg

try:
    import SpoutGL
    from SpoutGL import enums as gl_enums
    SPOUT_OK = True
    SPOUT_ERR = ""
except Exception as e:      # not on Windows / not installed
    SpoutGL = None
    SPOUT_OK = False
    SPOUT_ERR = str(e)


def list_senders():
    """[(name, width, height)] of every Spout sender currently published."""
    if not SPOUT_OK:
        return []
    out = []
    with SpoutGL.SpoutReceiver() as r:
        for name in r.getSenderList():
            try:
                info = r.getSenderInfo(name)
                out.append((name, int(info.width), int(info.height)))
            except Exception:
                out.append((name, 0, 0))
    return out


def safe_name(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40] or "camera"


class SenderRecorder(threading.Thread):
    """Receives one Spout sender and feeds raw BGRA frames to ffmpeg at a fixed fps.

    Runs on a wall-clock schedule: if the sender stalls, the last frame is repeated so
    every camera file stays on the same timeline as the others and the audio.
    A size change (camera resolution switched) closes the current file and opens a new part.
    """

    def __init__(self, session, name):
        super().__init__(daemon=True)
        self.session = session
        self.name = name
        self.tag = safe_name(name)
        self.stop_evt = threading.Event()
        self.frames = 0
        self.dups = 0
        self.size = None
        self.part = 0
        self.err = ""
        self.preview = None          # latest small JPEG for the web page
        self.started = None
        self._proc = None
        self._feed = None

    def _open(self, w, h, v0):
        s = self.session
        self.part += 1
        folder = os.path.join(s.dir, self.tag)
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        pattern = os.path.join(folder, f"{self.tag}_{stamp}_%03d.mp4")
        args = [s.ff, "-hide_banner", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{w}x{h}", "-framerate", str(s.fps), "-i", "-"]
        # game audio goes into this camera's own file, starting at the wall time of frame 0
        self._feed = s.audio.attach(v0) if s.audio else None
        if self._feed:
            args += audio.ffmpeg_input(self._feed.port) + audio.ffmpeg_output()
        args += ["-pix_fmt", "yuv420p"] + ffmpeg.video_args(s.encoder, s.quality) + \
            ffmpeg.segment_args(s.segment_minutes, pattern)
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, creationflags=ffmpeg.CREATE_NO_WINDOW)
        self.size = (w, h)
        s.log(f"[{self.name}] recording {w}x{h}{' + audio' if self._feed else ''} -> "
              f"{os.path.basename(pattern)} ({s.encoder})")
        s.mark_file(self.name, pattern, w, h)

    def _close(self):
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            if self._feed:
                self._feed.close()
                self._feed = None
            try:
                self._proc.wait(timeout=30)
            except Exception:
                self._proc.kill()
            self._proc = None

    def run(self):
        s = self.session
        fmt = gl_enums.GL_BGRA_EXT
        try:
            with SpoutGL.SpoutReceiver() as r:
                try:
                    r.createOpenGL()       # hidden GL context for this thread
                except Exception:
                    pass
                r.setReceiverName(self.name)
                buf = None
                last = None
                i = 0
                # each camera keeps its own clock from the moment it joins; the session log
                # records every file's wall-clock start so editors can line cameras up
                t0 = max(s.t0, time.time())
                self.started = t0
                last_preview = 0
                last_ok = time.time()
                while not self.stop_evt.is_set():
                    due = t0 + i / s.fps
                    now = time.time()
                    if now < due:
                        time.sleep(due - now)
                    ok = r.receiveImage(buf, fmt, False, 0)
                    if r.isUpdated():
                        w, h = r.getSenderWidth(), r.getSenderHeight()
                        if w > 0 and h > 0:
                            buf = array.array("B", bytes(w * h * 4))
                            if self.size and self.size != (w, h):
                                self._close()
                            last = None
                        continue
                    if buf is not None and ok:
                        last = buf
                        last_ok = time.time()
                    elif time.time() - last_ok > 5:
                        s.log(f"[{self.name}] sender gone - closing file")
                        break
                    if last is None:
                        i += 1
                        continue
                    if self._proc is None:
                        self._open(r.getSenderWidth(), r.getSenderHeight(), t0 + i / s.fps)
                    # catch up on the shared clock: duplicate frames if we fell behind
                    n = max(1, int((time.time() - t0) * s.fps) - i + 1)
                    data = last.tobytes() if hasattr(last, "tobytes") else bytes(last)
                    try:
                        for _ in range(n):
                            self._proc.stdin.write(data)
                    except (BrokenPipeError, OSError) as e:
                        self.err = f"encoder stopped: {e}"
                        s.log(f"[{self.name}] {self.err}")
                        self._close()
                    self.frames += n
                    self.dups += n - 1
                    i += n
                    if time.time() - last_preview > 1.0:
                        last_preview = time.time()
                        self._make_preview(data)
        except Exception as e:
            self.err = str(e)
            s.log(f"[{self.name}] receiver error: {e}")
        finally:
            self._close()

    def _make_preview(self, data):
        try:
            from PIL import Image
            import io
            w, h = self.size
            im = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1).convert("RGB")
            im.thumbnail((320, 180))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=70)
            self.preview = b.getvalue()
        except Exception:
            pass

    def stop(self):
        self.stop_evt.set()
