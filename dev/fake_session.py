"""Linux/CI test without VRChat: fake Spout sender (white flash each whole second) + fake loopback
(click each whole second, with a 3 s silent gap). Records N seconds, then reports per-file sync.

    python dev/fake_session.py 40        (needs ffmpeg on PATH, numpy, Pillow)
"""
import glob, os, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
import numpy as np
from studio import config, session

out = tempfile.mkdtemp(prefix="vrcam-test-")
ff = shutil.which("ffmpeg")
st = dict(config.DEFAULTS, output_dir=out, encoder="libx264", fps=30, segment_minutes=0.25, ffmpeg=ff, web_token="x")
S = session.Studio(st)
S.start()
time.sleep(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
S.stop()
for f in sorted(glob.glob(f"{out}/*/VRCamera/*.mp4")):
    v = subprocess.run([ff, "-v", "error", "-i", f, "-vf", "scale=8:8,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    lum = np.frombuffer(v, np.uint8).reshape(-1, 64).mean(1)
    vt = (np.where((lum[1:] > 128) & (lum[:-1] <= 128))[0] + 1) / 30.0
    a = np.frombuffer(subprocess.run([ff, "-v", "error", "-i", f, "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                                     capture_output=True).stdout, np.float32)
    at = (np.where((np.abs(a[1:]) > 0.3) & (np.abs(a[:-1]) <= 0.3))[0] + 1) / 48000.0
    offs = [round((at[np.abs(at - t).argmin()] - t) * 1000) for t in vt] if len(at) else []
    print(os.path.basename(f), "audio-minus-video ms:", offs)
print("output:", out)
