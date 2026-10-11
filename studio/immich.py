"""Upload finished recordings to an Immich server in the background.

A segment is uploaded once ffmpeg has closed it: in the session that is still recording that means
a newer segment exists in the same folder; in finished sessions every file qualifies. Files are
streamed (never read into memory), each session gets its own album, and what has been uploaded is
remembered in <output_dir>/.immich_uploaded.json so restarts never re-send anything. If the server
is unreachable the queue simply waits and drains when it comes back.
"""
import datetime
import http.client
import json
import os
import socket
import threading
import time
import uuid
from urllib.parse import quote, urlparse

VIDEO_EXT = (".mp4", ".mov", ".mkv")   # Immich has no audio-only assets, so .m4a stays local
SETTLE_S = 15                          # a file must be untouched this long before it counts as closed
STATE_NAME = ".immich_uploaded.json"


class Immich:
    def __init__(self, url, key, timeout=120):
        u = urlparse(url.rstrip("/"))
        self.https = u.scheme == "https"
        self.host = u.hostname
        self.port = u.port or (443 if self.https else 80)
        path = u.path.rstrip("/")
        self.base = path if path.endswith("/api") else path + "/api"
        self.key = key
        self.timeout = timeout

    def _conn(self):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        return cls(self.host, self.port, timeout=self.timeout)

    def _json(self, method, path, body=None):
        c = self._conn()
        try:
            data = json.dumps(body).encode() if body is not None else None
            hdr = {"x-api-key": self.key, "Accept": "application/json"}
            if data is not None:
                hdr["Content-Type"] = "application/json"
            c.request(method, self.base + path, body=data, headers=hdr)
            r = c.getresponse()
            raw = r.read()
            if r.status >= 300:
                raise RuntimeError(f"{method} {path} -> HTTP {r.status} {raw[:200]!r}")
            return json.loads(raw) if raw else None
        finally:
            c.close()

    def ping(self):
        try:
            return (self._json("GET", "/server/ping") or {}).get("res") == "pong"
        except (OSError, RuntimeError, ValueError):
            return False

    def album_id(self, name):
        for a in self._json("GET", "/albums") or []:
            if a.get("albumName") == name:
                return a["id"]
        return self._json("POST", "/albums", {"albumName": name})["id"]

    def add_to_album(self, album, asset_ids):
        self._json("PUT", f"/albums/{quote(album)}/assets", {"ids": asset_ids})

    def upload(self, path, device_asset_id, device_id, created):
        """Stream one file as multipart/form-data. Returns (asset_id, "created"|"duplicate")."""
        boundary = uuid.uuid4().hex
        iso_c = datetime.datetime.fromtimestamp(created, datetime.timezone.utc).isoformat()
        iso_m = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc).isoformat()
        fields = {"deviceAssetId": device_asset_id, "deviceId": device_id,
                  "fileCreatedAt": iso_c, "fileModifiedAt": iso_m, "isFavorite": "false"}
        head = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in fields.items())
        fn = os.path.basename(path).replace('"', "_")
        head += (f'--{boundary}\r\nContent-Disposition: form-data; name="assetData"; filename="{fn}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        size = len(head) + os.path.getsize(path) + len(tail)
        c = self._conn()
        try:
            c.putrequest("POST", self.base + "/assets")
            c.putheader("x-api-key", self.key)
            c.putheader("Accept", "application/json")
            c.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            c.putheader("Content-Length", str(size))
            c.endheaders()
            c.send(head)
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    c.send(chunk)
            c.send(tail)
            r = c.getresponse()
            raw = r.read()
            if r.status >= 300:
                raise RuntimeError(f"upload {fn} -> HTTP {r.status} {raw[:200]!r}")
            resp = json.loads(raw)
            return resp.get("id"), resp.get("status", "created")
        finally:
            c.close()


def _created(path):
    st = os.stat(path)
    born = getattr(st, "st_birthtime", None)
    if born:
        return born
    return st.st_ctime if os.name == "nt" else st.st_mtime


class Uploader(threading.Thread):
    def __init__(self, studio):
        super().__init__(daemon=True)
        self.studio = studio
        self.state = {}
        self.online = None
        self.err = ""
        self.uploading = ""
        self.pending_n = 0
        self.done_n = 0
        self.last = ""
        self._albums = {}
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._load()

    # -- settings / state
    @property
    def settings(self):
        return self.studio.settings

    def enabled(self):
        return bool(self.settings.get("immich_url") and self.settings.get("immich_api_key"))

    def _state_path(self):
        return os.path.join(self.settings["output_dir"], STATE_NAME)

    def _load(self):
        try:
            with open(self._state_path(), encoding="utf-8") as f:
                self.state = json.load(f)
        except (OSError, ValueError):
            self.state = {}
        self.done_n = len(self.state)

    def _save(self):
        p = self._state_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=0)
        os.replace(tmp, p)

    def kick(self):
        self._wake.set()

    # -- what is ready to go
    def ready_files(self):
        root = self.settings["output_dir"]
        if not os.path.isdir(root):
            return []
        cur = self.studio.session.dir if self.studio.session else None
        now = time.time()
        out = []
        for sess in sorted(os.listdir(root)):
            sdir = os.path.join(root, sess)
            if not os.path.isdir(sdir):
                continue
            for folder, _, files in os.walk(sdir):
                vids = [os.path.join(folder, f) for f in files if f.lower().endswith(VIDEO_EXT)]
                if not vids:
                    continue
                live = None
                if cur and os.path.normcase(sdir) == os.path.normcase(cur):
                    live = max(vids, key=os.path.getmtime)   # the segment ffmpeg is still writing
                for v in sorted(vids):
                    rel = os.path.relpath(v, root).replace("\\", "/")
                    if rel in self.state or v == live:
                        continue
                    try:
                        if now - os.path.getmtime(v) < SETTLE_S or os.path.getsize(v) < 1024:
                            continue
                    except OSError:
                        continue
                    out.append((sess, rel, v))
        return out

    def has_pending(self, session_dir):
        """Storage pruning asks this so it never deletes a session that isn't in Immich yet."""
        if not self.enabled():
            return False
        root = self.settings["output_dir"]
        for folder, _, files in os.walk(session_dir):
            for f in files:
                if f.lower().endswith(VIDEO_EXT):
                    rel = os.path.relpath(os.path.join(folder, f), root).replace("\\", "/")
                    if rel not in self.state:
                        return True
        return False

    # -- loop
    def run(self):
        while True:
            self._wake.wait(10)
            self._wake.clear()
            if not self.enabled():
                self.online = None
                continue
            try:
                self._pass()
            except Exception as e:  # keep the thread alive no matter what
                self._fail(str(e))

    def _fail(self, msg):
        if msg != self.err:
            self.studio.log(f"immich: {msg}")
        self.err = msg
        self.uploading = ""

    def _pass(self):
        st = self.settings
        api = Immich(st["immich_url"], st["immich_api_key"])
        files = self.ready_files()
        self.pending_n = len(files)
        if not files:
            self.online = api.ping()
            return
        if not api.ping():
            self.online = False
            self._fail(f"server unreachable ({st['immich_url']}); {len(files)} file(s) waiting")
            return
        self.online = True
        device = "vrcam-studio-" + socket.gethostname()
        for sess, rel, path in files:
            self.uploading = rel
            asset, status = api.upload(path, rel, device, _created(path))
            album_name = st.get("immich_album") or ""
            if asset and album_name:
                name = album_name.replace("{session}", sess)
                if name not in self._albums:
                    self._albums[name] = api.album_id(name)
                api.add_to_album(self._albums[name], [asset])
            self.state[rel] = asset or status
            self._save()
            self.done_n = len(self.state)
            self.pending_n -= 1
            self.last = rel
            self.uploading = ""
            if self.err:
                self.studio.log("immich: back online")
            self.err = ""
            mb = os.path.getsize(path) / 1e6
            self.studio.log(f"immich: {status} {rel} ({mb:.0f} MB)")

    def status(self):
        return {"enabled": self.enabled(), "online": self.online, "pending": self.pending_n,
                "uploaded": self.done_n, "uploading": self.uploading, "last": self.last, "err": self.err,
                "url": self.settings.get("immich_url", ""), "has_key": bool(self.settings.get("immich_api_key")),
                "album": self.settings.get("immich_album", "")}
