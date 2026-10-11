import time, numpy as np
R = 48000
class _Rec:
    def __init__(s, n): s.t = time.time(); s.stalled = False
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def record(s, numframes):
        end = s.t + numframes / R
        now = time.time()
        if end > now: time.sleep(end - now)
        # simulate WASAPI loopback silence: no packets between t0+6 and t0+9
        if not s.stalled and int(s.t) % 30 == 6:
            s.stalled = True; time.sleep(3); s.t = time.time(); return np.zeros((0, 2), "f4")
        ts = s.t + np.arange(numframes) / R
        x = np.where((ts % 1.0) < 0.005, 0.9, 0.0).astype("f4")   # 5 ms click at each whole second
        s.t = end
        return np.stack([x, x], 1)
class _Mic:
    def recorder(self, samplerate, channels, blocksize): return _Rec(blocksize)
class _Spk: name = "fake speaker"
def default_speaker(): return _Spk()
def get_microphone(id, include_loopback): return _Mic()
