"""python -m studio            -> run the studio (web page + recorder)
python -m studio doctor     -> check Spout / ffmpeg / encoders / audio / OSC and print a report"""
import sys
import threading
import webbrowser

from . import config


def doctor():
    import platform
    s = config.load()
    print("VRCam Studio doctor")
    print("python", sys.version.split()[0], platform.platform())
    try:
        from . import ffmpeg
        ff = ffmpeg.find(s)
        print("ffmpeg:", ff)
        for enc in ffmpeg.CANDIDATES:
            print(f"  {enc:12s}", "OK" if ffmpeg.works(ff, enc) else "-")
        r = ffmpeg.run([ff, "-hide_banner", "-filters"])
        print("  ddagrab (POV capture):", "OK" if "ddagrab" in r.stdout else "missing")
    except Exception as e:
        print("ffmpeg: FAIL", e)
    from . import spout
    print("SpoutGL:", "OK" if spout.SPOUT_OK else "FAIL " + spout.SPOUT_ERR)
    if spout.SPOUT_OK:
        snd = spout.list_senders()
        print(f"  senders ({len(snd)}):")
        for n, w, h in snd:
            print(f"    {n}  {w}x{h}")
        if not snd:
            print("    none - open the VRChat camera, Stream mode, Spout Stream on")
    try:
        import soundcard as sc
        print("audio loopback:", sc.default_speaker().name)
    except Exception as e:
        print("audio: FAIL", e)
    import socket
    try:
        t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t.bind(("127.0.0.1", int(s["osc_listen_port"])))
        t.close()
        print(f"OSC listen port {s['osc_listen_port']}: free")
    except OSError:
        print(f"OSC listen port {s['osc_listen_port']}: IN USE (another OSC app) - camera control still works")
    if s.get("immich_url") and s.get("immich_api_key"):
        from . import immich
        api = immich.Immich(s["immich_url"], s["immich_api_key"], timeout=8)
        try:
            api._json("GET", "/albums")
            print("immich:", s["immich_url"], "OK (key works)")
        except Exception as e:
            print("immich:", s["immich_url"], "FAIL", e)
    else:
        print("immich: off (set immich_url + immich_api_key)")
    print("output:", s["output_dir"])


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        return doctor()
    settings = config.load()
    from .osc import OSC
    from .session import Studio
    from .web import serve
    studio = Studio(settings)
    osc = OSC(settings["osc_host"], int(settings["osc_send_port"]), int(settings["osc_listen_port"]))
    srv = serve(studio, osc, settings)
    host = settings["web_host"]
    url = f"http://127.0.0.1:{settings['web_port']}/"
    print(f"\n  VRCam Studio running:  {url}")
    if host == "0.0.0.0":
        print(f"  From your phone:       http://<this-pc-ip>:{settings['web_port']}/?k={settings['web_token']}")
    print("  Ctrl+C to stop (finishes the files cleanly)\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("stopping...")
        studio.stop()


if __name__ == "__main__":
    main()
