# VRCam Studio

Record every VRChat camera angle at the same time, each to its own file, while you keep playing normally.

VRChat's camera can stream over **Spout**, which shares the camera's GPU image directly with other apps. This app picks up every Spout camera VRChat publishes and records each one in the background. Nothing is drawn over your screen or headset, and nothing steals focus. You play; it records.

- **Multi-camera:** with the Camera Dolly's *Multi* streaming mode, VRChat runs up to **4 cameras at once**. Each one is a separate Spout feed, recorded here as a separate file.
- **Camera rig:** place up to 4 cameras around you on a top-down dial (angle, distance, height) and push it into VRChat with one click. The rig is player-relative, so it follows you.
- **Always-on:** recording starts automatically whenever a VRChat camera appears.
- **Crash-safe:** files are split into 5-minute segments, so a crash or power cut loses at most the current few minutes.
- **Hardware encoding:** NVIDIA NVENC, AMD AMF or Intel QSV, picked automatically, with CPU x264 as a fallback.
- **Game audio:** recorded via WASAPI loopback, i.e. everything you hear.
- **Optional POV:** also record your own screen.
- **Phone remote:** control the camera (mode, Look-at-me, zoom, framing, exposure, photo) from any browser over OSC.

## Requirements

- Windows 10/11 with a GPU that runs VRChat.
- VRChat desktop or PC VR. Quest standalone has no Spout.
- **VRC+** for the Camera Dolly and Multi streaming. Without VRC+ you still get the single Stream Camera, recorded the same way.
- OSC enabled in VRChat: Action Menu → OSC → Enabled.

## Install

```
git clone https://github.com/theSLOP-dev/VRCAM-STUDIO.git
cd VRCAM-STUDIO
install.bat
```

`install.bat` installs Python 3.12 if it's missing (via winget), creates a virtual environment, installs the Python packages, downloads ffmpeg into `tools\ffmpeg`, and then runs `doctor`, which prints what works on your machine.

## Use

1. `run.bat`. The control page opens at http://127.0.0.1:8480.
2. In VRChat, open **Camera → Stream Camera** and make sure **Spout Stream** is ticked. It appears under *Cameras* on the page.
3. Press **● REC**, or turn on **Always-on** and forget about it.
4. **Multi-camera:**
   - One-time setup in VRChat: Camera → Dolly → settings → Streaming **Multi**, Loop **Repeat**.
   - On the page, place up to 4 cameras on the rig dial and click **Apply rig in VRChat**.
   - Each camera shows up as its own feed and is recorded to its own file.

Recordings go to `Videos\VRCam Studio\<date_time>\`:

```
<sender name>\<sender>_<time>_000.mp4, _001.mp4 ...   one folder per camera, 5-min segments
audio\audio_<time>_000.m4a ...                       game audio
pov\pov_<time>_000.mp4 ...                           your screen (if enabled)
session.json                                         wall-clock start of every file, for syncing in an editor
```

All files in a session start within a few frames of each other, and `session.json` has each file's exact start time if you need to line them up.

## Phone control

In `settings.json`, set `"web_host": "0.0.0.0"` and restart. Then open `http://<pc-ip>:8480/?k=<web_token>` on your phone. The token is in `settings.json`; localhost doesn't need it.

## Settings (`settings.json`, created on first run)

| key | default | |
|---|---|---|
| `output_dir` | `~/Videos/VRCam Studio` | where sessions go |
| `fps` | 60 | recording frame rate |
| `encoder` | auto | or `h264_nvenc`, `hevc_nvenc`, `h264_amf`, `h264_qsv`, `libx264` |
| `quality` | 20 | lower = better / bigger (18-26) |
| `segment_minutes` | 5 | file split length |
| `always_on` | false | auto-record whenever a camera exists |
| `record_audio` | true | system audio loopback |
| `record_pov` | false | record your own monitor too |
| `max_storage_gb` | 0 | >0: delete oldest sessions past this size |
| `sender_filter` | "" | only record senders whose name contains this |
| `osc_listen_port` | 9001 | 0 to disable if another OSC app needs 9001 |

## Troubleshooting

- Run `doctor.bat` and read the report: Spout, the encoders, the camera senders it can see, audio, and OSC ports.
- **No cameras listed:** in VRChat, open the camera in **Stream** mode and tick **Spout Stream**.
- **OSC port in use:** another app (face tracking, etc.) is on 9001. Camera control still works because sending uses 9000.

## How it works

`studio/spout.py` opens one SpoutGL receiver per sender in its own thread, reads BGRA frames, and pipes them into an ffmpeg process per camera. Each camera runs on a fixed wall clock: if VRChat skips a frame, the last frame is repeated, so files never drift. `studio/rig.py` writes a Camera Dolly JSON in the same format as VRChat's own export (player-local points, one path per camera) and loads it via OSC (`/dolly/Import`, `/dolly/Play`).

MIT license.
