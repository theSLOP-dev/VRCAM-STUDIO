"""Studio: owns recording sessions, watches for Spout cameras, enforces storage cap."""
import json
import os
import shutil
import threading
import time

from . import ffmpeg, spout
from .audio import AudioRecorder, PovRecorder


class Session:
    def __init__(self, studio):
        st = studio.settings
        self.studio = studio
        self.ff = studio.ff
        self.encoder = studio.encoder
        self.fps = int(st["fps"])
        self.quality = st["quality"]
        self.segment_minutes = float(st["segment_minutes"])
        self.t0 = time.time()
        self.dir = os.path.join(st["output_dir"], time.strftime("%Y-%m-%d_%H-%M-%S"))
        os.makedirs(self.dir, exist_ok=True)
        self.recorders = {}
        self.audio = None
        self.pov = None
        self.files = []
        self._lock = threading.Lock()

    def log(self, msg):
        self.studio.log(msg)

    def mark_file(self, source, pattern, w, h):
        """Wall-clock start of every file, so all angles + audio can be lined up in an editor."""
        with self._lock:
            self.files.append({"source": source, "pattern": os.path.relpath(pattern, self.dir),
                               "start_unix": round(time.time(), 3),
                               "offset_s": round(time.time() - self.t0, 3), "size": [w, h]})
            self._write_meta()

    def _write_meta(self):
        meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.t0)),
                "start_unix": self.t0, "fps": self.fps, "encoder": self.encoder, "files": self.files}
        with open(os.path.join(self.dir, "session.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)

    def add_sender(self, name):
        r = self.recorders.get(name)
        if r and r.is_alive():
            return
        r = spout.SenderRecorder(self, name)
        self.recorders[name] = r
        r.start()

    def start(self):
        st = self.studio.settings
        if st.get("record_audio"):
            self.audio = AudioRecorder(self)
            self.audio.start()
        if st.get("record_pov"):
            self.pov = PovRecorder(self, int(st.get("pov_monitor", 0)))
            self.pov.start()
        self.log(f"session started -> {self.dir}")

    def stop(self):
        for r in self.recorders.values():
            r.stop()
        for r in self.recorders.values():
            r.join(timeout=30)
        if self.audio:
            self.audio.stop()
            self.audio.join(timeout=20)
        if self.pov:
            self.pov.stop()
        self._write_meta()
        self.log(f"session saved ({round(time.time() - self.t0)}s) -> {self.dir}")

    def status(self):
        return {
            "dir": self.dir, "secs": round(time.time() - self.t0, 1),
            "cams": [{"name": n, "frames": r.frames, "dups": r.dups, "alive": r.is_alive(),
                      "size": "%dx%d" % r.size if r.size else None, "err": r.err}
                     for n, r in self.recorders.items()],
            "audio": None if not self.audio else {"alive": self.audio.is_alive(), "err": self.audio.err,
                                                  "level": round(self.audio.level, 3)},
            "pov": bool(self.pov),
        }


class Studio:
    def __init__(self, settings):
        self.settings = settings
        self.logs = []
        self.ff = ffmpeg.find(settings)
        self.encoder = ffmpeg.pick_encoder(self.ff, settings.get("encoder", "auto"))
        self.session = None
        self.senders = []
        self.lock = threading.Lock()
        self.log(f"ffmpeg: {self.ff}")
        self.log(f"encoder: {self.encoder}")
        if not spout.SPOUT_OK:
            self.log(f"Spout unavailable: {spout.SPOUT_ERR}")
        threading.Thread(target=self._watch, daemon=True).start()
        if settings.get("always_on"):
            self.start()

    def log(self, msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        self.logs = (self.logs + [line])[-200:]

    def _wanted(self, name):
        f = self.settings.get("sender_filter", "")
        return not f or f.lower() in name.lower()

    def _watch(self):
        last_prune = 0
        while True:
            try:
                self.senders = spout.list_senders()
            except Exception as e:
                self.senders = []
                self.log(f"sender scan failed: {e}")
            with self.lock:
                if self.session is None and self.settings.get("always_on") and self.senders:
                    self._start_locked()
                if self.session:
                    for name, w, h in self.senders:
                        if self._wanted(name):
                            self.session.add_sender(name)
            if time.time() - last_prune > 60:
                last_prune = time.time()
                self.prune()
            time.sleep(1.0)

    def _start_locked(self):
        self.session = Session(self)
        self.session.start()
        for name, w, h in self.senders:
            if self._wanted(name):
                self.session.add_sender(name)

    def start(self):
        with self.lock:
            if self.session is None:
                self._start_locked()
        return True

    def stop(self):
        with self.lock:
            s, self.session = self.session, None
        if s:
            s.stop()
        return True

    def prune(self):
        cap = float(self.settings.get("max_storage_gb") or 0)
        root = self.settings["output_dir"]
        if cap <= 0 or not os.path.isdir(root):
            return
        current = self.session.dir if self.session else None
        dirs = sorted(os.path.join(root, d) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))

        def size(p):
            return sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(p) for f in fs)
        total = sum(size(d) for d in dirs)
        for d in dirs:
            if total <= cap * 1e9:
                break
            if d == current:
                continue
            sz = size(d)
            shutil.rmtree(d, ignore_errors=True)
            total -= sz
            self.log(f"storage cap: deleted old session {os.path.basename(d)}")

    def status(self):
        return {
            "recording": self.session is not None,
            "session": self.session.status() if self.session else None,
            "senders": [{"name": n, "w": w, "h": h, "recorded": self._wanted(n)} for n, w, h in self.senders],
            "spout_ok": spout.SPOUT_OK, "spout_err": spout.SPOUT_ERR,
            "encoder": self.encoder, "always_on": bool(self.settings.get("always_on")),
            "output_dir": self.settings["output_dir"], "log": self.logs[-12:],
        }

    def preview(self, name):
        s = self.session
        if s and name in s.recorders:
            return s.recorders[name].preview
        return None
