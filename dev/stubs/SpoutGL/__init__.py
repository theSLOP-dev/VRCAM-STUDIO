import time
class _E: GL_BGRA_EXT = 0x80E1
enums = _E()
W, H = 320, 180
class _Info:
    width, height = W, H
class SpoutReceiver:
    def __enter__(self): self._upd = True; return self
    def __exit__(self, *a): pass
    def getSenderList(self): return ["VRCamera"]
    def getSenderInfo(self, n): return _Info()
    def createOpenGL(self): pass
    def setReceiverName(self, n): pass
    def getSenderWidth(self): return W
    def getSenderHeight(self): return H
    def isUpdated(self):
        u, self._upd = self._upd, False
        return u
    def receiveImage(self, buf, fmt, invert, fbo):
        if buf is None: return False
        t = time.time()
        v = 255 if (t % 1.0) < 1/30 else 0      # one white frame at each whole second
        buf[:] = __import__("array").array("B", bytes([v]) * len(buf))
        return True
