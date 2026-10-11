import os, time
N = int(os.environ.get("FAKE_CAMS", 1))
COL = [(40, 40, 200), (40, 160, 40), (200, 60, 160), (200, 160, 30)]
class _E: GL_BGRA_EXT = 0x80E1
enums = _E()
W, H = 320, 180
class _Info:
    width, height = W, H
class SpoutReceiver:
    def __enter__(self): self._upd = True; return self
    def __exit__(self, *a): pass
    def getSenderList(self): return ["VRCamera"] + [f"VRCDolly{i}" for i in range(1, N)]
    def getSenderInfo(self, n): return _Info()
    def createOpenGL(self): pass
    def setReceiverName(self, n): self.n = n
    def getSenderWidth(self): return W
    def getSenderHeight(self): return H
    def isUpdated(self):
        u, self._upd = self._upd, False
        return u
    def receiveImage(self, buf, fmt, invert, fbo):
        if buf is None: return False
        t = time.time()
        i = 0 if self.n == "VRCamera" else int(self.n[-1])
        if (t % 1.0) < 1/30:                    # one white frame at each whole second
            px = bytes([255, 255, 255, 255])
        else:
            b, g, r = COL[i % 4]
            px = bytes([b, g, r, 255]) if N > 1 else bytes(4)
        buf[:] = __import__("array").array("B", px * (len(buf) // 4))
        return True
