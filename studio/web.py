"""Control page + JSON API. Localhost needs no token; other devices need ?k=<web_token>."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, rig

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# VRChat user-camera OSC endpoints the page may set -> type
UCAM = {"Mode": int, "Zoom": float, "LookAtMe": bool, "LookAtMeXOffset": float, "LookAtMeYOffset": float,
        "Flying": bool, "Lock": bool, "SmoothMovement": bool, "SmoothingStrength": float,
        "AutoLevelPitch": bool, "AutoLevelRoll": bool, "ShowUIInCamera": bool, "LocalPlayer": bool,
        "RemotePlayer": bool, "Environment": bool, "GreenScreen": bool, "Streaming": bool,
        "FlySpeed": float, "TurnSpeed": float, "Exposure": float, "FocalDistance": float,
        "Aperture": float, "Duration": float}
BUTTONS = {"Capture", "CaptureDelayed", "Close"}


def make_handler(studio, osc, settings):
    rig_state = {"cams": [dict(rig.PRESETS["front"], name="front"),
                          dict(rig.PRESETS["3/4 left"], name="3/4 left"),
                          dict(rig.PRESETS["wide"], name="wide")]}
    ucam = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _ok(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            local = self.client_address[0] in ("127.0.0.1", "::1")
            return u.path, q, local or q.get("k") == settings["web_token"]

        def do_GET(self):
            p, q, ok = self._ok()
            if not ok:
                return self._send(403, {"error": "add ?k=<web_token> from settings.json"})
            if p == "/":
                with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if p == "/api/status":
                return self._send(200, dict(studio.status(), rig=rig_state["cams"], ucam=ucam,
                                            presets=rig.PRESETS, osc_err=osc.listen_err,
                                            dolly_playing=osc.values.get("/dolly/Play")))
            if p == "/api/preview":
                img = studio.preview(q.get("name", ""))
                if img:
                    return self._send(200, img, "image/jpeg")
                return self._send(404, {"error": "no preview"})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            p, q, ok = self._ok()
            if not ok:
                return self._send(403, {"error": "token"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                b = {}
            if p == "/api/rec/start":
                return self._send(200, {"ok": studio.start()})
            if p == "/api/rec/stop":
                threading.Thread(target=studio.stop, daemon=True).start()
                return self._send(200, {"ok": True})
            if p == "/api/always_on":
                settings["always_on"] = bool(b.get("on"))
                config.save(settings)
                if settings["always_on"]:
                    studio.start()
                return self._send(200, {"ok": True, "always_on": settings["always_on"]})
            if p == "/api/ucam":
                k, v = b.get("k"), b.get("v")
                if k in BUTTONS:
                    osc.send("/usercamera/" + k, True)
                    threading.Timer(0.15, lambda: osc.send("/usercamera/" + k, False)).start()
                    return self._send(200, {"ok": True})
                if k not in UCAM:
                    return self._send(400, {"error": "bad key"})
                v = UCAM[k](v)
                osc.send("/usercamera/" + k, v)
                ucam[k] = v
                return self._send(200, {"ok": True, "ucam": ucam})
            if p == "/api/rig":
                cams = b.get("cams")
                if isinstance(cams, list):
                    clean = []
                    for c in cams[:4]:
                        clean.append({"name": str(c.get("name", "cam"))[:20],
                                      "angle": float(c.get("angle", 0)) % 360,
                                      "dist": max(0.3, min(30.0, float(c.get("dist", 2.5)))),
                                      "height": max(-2.0, min(15.0, float(c.get("height", 1.5)))),
                                      "zoom": max(20.0, min(150.0, float(c.get("zoom", 45))))})
                    rig_state["cams"] = clean
                return self._send(200, {"ok": True, "cams": rig_state["cams"]})
            if p == "/api/rig/apply":
                fp = rig.write(rig_state["cams"])
                osc.send("/dolly/Play", False)
                time.sleep(0.2)
                # VRChat docs disagree on whether /dolly/Import takes a file path or the JSON
                # itself, so send the path, then the JSON (a failed import is a no-op).
                osc.send("/dolly/Import", fp)
                time.sleep(0.4)
                osc.send("/dolly/Import", json.dumps(rig.build(rig_state["cams"]), separators=(",", ":")))
                time.sleep(0.5)
                osc.send("/dolly/Play", True)
                studio.log(f"rig applied: {len(rig_state['cams'])} cameras -> {fp} "
                           f"(needs VRC+, Dolly Streaming=Multi; watch for new cameras above)")
                return self._send(200, {"ok": True, "file": fp})
            if p == "/api/dolly/play":
                osc.send("/dolly/Play", bool(b.get("on", True)))
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    return H


def serve(studio, osc, settings):
    srv = ThreadingHTTPServer((settings["web_host"], int(settings["web_port"])), make_handler(studio, osc, settings))
    return srv
