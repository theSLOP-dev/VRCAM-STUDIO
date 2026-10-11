"""Minimal OSC client/listener for VRChat (no dependencies)."""
import socket
import struct
import threading


def _pad(b):
    return b + b"\0" * (4 - len(b) % 4)


def encode(addr, *vals):
    tags = ","
    body = b""
    for v in vals:
        if isinstance(v, bool):
            tags += "T" if v else "F"
        elif isinstance(v, int):
            tags += "i"
            body += struct.pack(">i", v)
        elif isinstance(v, float):
            tags += "f"
            body += struct.pack(">f", v)
        else:
            tags += "s"
            body += _pad(str(v).encode("utf-8"))
    return _pad(addr.encode()) + _pad(tags.encode()) + body


def decode(data):
    try:
        end = data.index(b"\0")
        addr = data[:end].decode()
        i = (end // 4 + 1) * 4
        end = data.index(b"\0", i)
        tags = data[i + 1:end].decode()
        i = (end // 4 + 1) * 4
        vals = []
        for t in tags:
            if t == "i":
                vals.append(struct.unpack(">i", data[i:i + 4])[0]); i += 4
            elif t == "f":
                vals.append(struct.unpack(">f", data[i:i + 4])[0]); i += 4
            elif t == "s":
                end = data.index(b"\0", i)
                vals.append(data[i:end].decode("utf-8", "replace")); i = (end // 4 + 1) * 4
            elif t == "T":
                vals.append(True)
            elif t == "F":
                vals.append(False)
        return addr, vals
    except (ValueError, struct.error):
        return None, []


class OSC:
    def __init__(self, host="127.0.0.1", send_port=9000, listen_port=9001):
        self.addr = (host, send_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.values = {}           # latest value of every address VRChat sent us
        self.listen_port = listen_port
        self.listen_err = ""
        self._waiters = {}
        if listen_port:
            threading.Thread(target=self._listen, daemon=True).start()

    def send(self, addr, *vals):
        try:
            self.sock.sendto(encode(addr, *vals), self.addr)
        except OSError:
            pass

    def _listen(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", self.listen_port))
        except OSError as e:
            self.listen_err = f"can't listen on {self.listen_port} ({e}) - another OSC app may own it"
            return
        while True:
            data, _ = s.recvfrom(65535)
            addr, vals = decode(data)
            if addr and (addr.startswith("/usercamera") or addr.startswith("/dolly") or addr == "/avatar/change"):
                self.values[addr] = vals
                ev = self._waiters.pop(addr, None)
                if ev:
                    ev.set()

    def wait_for(self, addr, timeout=5.0):
        ev = threading.Event()
        self._waiters[addr] = ev
        ev.wait(timeout)
        return self.values.get(addr)
