"""System audio (everything you hear in VRChat) via WASAPI loopback.

The loopback capture is put on the wall clock (sample k <-> a0 + k/RATE) and fanned out:
- into every camera's ffmpeg over a local TCP socket, starting at the exact wall-clock time of that
  camera's first frame, so each camera file carries its own in-sync audio track;
- into a separate audio/ track (handy as a master for editing).
WASAPI loopback delivers nothing while nothing is playing, so gaps are filled with silence on the
clock, and the device clock drifting ahead of the system clock is trimmed. Either way the audio
stays locked to the video, which runs on the same system clock.
"""
import os
import queue
import socket
import subprocess
import threading
import time

from . import ffmpeg

RATE = 48000
BLOCK = 1024
FRAME = 8                  # bytes per sample frame: 2 channels x float32
LAG = int(0.15 * RATE)     # how far behind real time silence-padding runs (covers capture latency)
JITTER = int(0.04 * RATE)  # capture timing noise tolerated before re-aligning to the clock
KEEP = 10 * RATE           # history kept so a camera that starts late still gets its first seconds


def ffmpeg_input(port):
    """ffmpeg input args for a camera's audio feed (connects to AudioRecorder.attach's port)."""
    return ["-thread_queue_size", "4096", "-f", "f32le", "-ar", str(RATE), "-ac", "2",
            "-i", f"tcp://127.0.0.1:{port}"]


def ffmpeg_output():
    return ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]


class _Sink(threading.Thread):
    """Writes queued audio to one consumer (a socket or a pipe) without ever blocking the clock."""

    def __init__(self, write, close, k):
        super().__init__(daemon=True)
        self.write, self._close, self.k = write, close, k
        self.q = queue.Queue()
        self.dead = False

    def run(self):
        while True:
            b = self.q.get()
            if b is None:
                break
            try:
                self.write(b)
            except OSError:
                break
        self.dead = True
        try:
            self._close()
        except OSError:
            pass

    def close(self):
        self.q.put(None)


class _Feed:
    def __init__(self, bus, v0):
        self.sink = None
        self.closed = False
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.srv.settimeout(30)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._accept, args=(bus, v0), daemon=True).start()

    def _accept(self, bus, v0):
        try:
            conn, _ = self.srv.accept()
        except OSError:
            return
        finally:
            self.srv.close()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sink = _Sink(conn.sendall, conn.close, 0)
        bus._add(self.sink, bus._k(v0))
        if self.closed:
            self.sink.close()

    def close(self):
        self.closed = True
        self.srv.close()
        if self.sink:
            self.sink.close()


class AudioRecorder(threading.Thread):
    def __init__(self, session):
        super().__init__(daemon=True)
        self.session = session
        self.stop_evt = threading.Event()
        self.ready = threading.Event()     # set once the clock is running (or audio failed)
        self.err = ""
        self.started = None
        self.level = 0.0
        self.a0 = None                     # wall time of sample 0
        self.base = 0                      # sample index of buf[0]
        self.w = 0                         # sample index just past the newest sample
        self.buf = bytearray()
        self.sinks = []
        self.lock = threading.Lock()
        self.offset = float(session.studio.settings.get("audio_offset_ms", 0)) / 1000

    def _k(self, t):
        return int((t - self.a0) * RATE)

    # -- consumers
    def _add(self, sink, k):
        with self.lock:
            sink.k = k
            self.sinks.append(sink)
        sink.start()

    def attach(self, v0):
        """Open a socket for one camera's ffmpeg; its audio starts at wall time v0 (the camera's
        first frame). Returns a Feed (.port for ffmpeg, .close() when the file ends), or None."""
        if not self.ready.wait(3) or self.a0 is None or self.stop_evt.is_set():
            return None
        return _Feed(self, v0)

    def detach_all(self):
        with self.lock:
            sinks, self.sinks = self.sinks, []
        for s in sinks:
            s.close()

    # -- clock
    def _pump(self):
        while not self.stop_evt.wait(0.02):
            self._tick()
        self._tick()

    def _tick(self):
        with self.lock:
            if self.a0 is None:
                return
            target = self._k(time.time()) - LAG
            if self.w < target:                                  # capture silent/late: pad
                self.buf += bytes((target - self.w) * FRAME)
                self.w = target
            self.sinks = [s for s in self.sinks if not s.dead]
            for s in self.sinks:
                if s.k < self.base:                              # wants audio we no longer hold
                    s.q.put(bytes((self.base - s.k) * FRAME))
                    s.k = self.base
                if s.k < self.w:
                    lo = (s.k - self.base) * FRAME
                    s.q.put(bytes(self.buf[lo:(self.w - self.base) * FRAME]))
                    s.k = self.w
            keep = self.w - KEEP
            if keep > self.base:
                del self.buf[:(keep - self.base) * FRAME]
                self.base = keep

    def run(self):
        s = self.session
        try:
            import numpy as np
            import soundcard as sc
            spk = sc.default_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
        except Exception as e:
            self.err = f"audio unavailable: {e}"
            s.log(self.err)
            self.ready.set()
            return
        threading.Thread(target=self._pump, daemon=True).start()
        try:
            with mic.recorder(samplerate=RATE, channels=2, blocksize=BLOCK) as rec:
                self.started = time.time()
                s.log(f"[audio] recording '{spk.name}' (loopback) into every camera file")
                while not self.stop_evt.is_set():
                    data = rec.record(numframes=BLOCK)
                    now = time.time()
                    if not data.size:
                        continue
                    if data.ndim == 1:
                        data = np.repeat(data[:, None], 2, axis=1)
                    n = len(data)
                    self.level = float(abs(data).max())
                    b = data[:, :2].astype("<f4").tobytes()
                    with self.lock:
                        if self.a0 is None:
                            self.a0 = now - n / RATE - self.offset
                            self._start_track()
                            self.ready.set()
                        at = self._k(now) - n                    # where this block belongs in time
                        if self.w < at - JITTER:                 # resumed after silence: jump to now
                            self.buf += bytes((at - self.w) * FRAME)
                            self.w = at
                        elif self.w > at + LAG:                  # device clock ahead: drop block
                            continue
                        self.buf += b
                        self.w += n
        except Exception as e:
            self.err = f"audio error: {e}"
            s.log(self.err)
        finally:
            self.ready.set()
            self.stop_evt.set()
            self.detach_all()

    def _start_track(self):
        """Separate audio/ track, fed from the same clock (called with the lock held)."""
        s = self.session
        if not s.studio.settings.get("audio_track_file", True):
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

        def close():
            p.stdin.close()
            p.wait(timeout=20)
        sink = _Sink(p.stdin.write, close, 0)
        self.sinks.append(sink)
        sink.start()
        s.mark_file("audio", pattern, 0, 0)

    def stop(self):
        self.stop_evt.set()
        self.join(2)            # loopback can block while nothing plays; don't wait on it
        self.detach_all()


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
