# Development and demo cameras

Real-time footage for NestWatch without buying hardware: [MediaMTX](https://github.com/bluenviron/mediamtx) (MIT) turns
looped staged clips and publisher-authorized public webcams into ordinary RTSP cameras, and the API analyzes up to 4 of
them at once (SPEC SRC-4, SRC-5). Everything here is for development and the demo; none of it is daycare footage.

```sh
pipx install streamlink          # or: uv tool install streamlink   (public webcam relays)
brew install ffmpeg              # or: sudo apt-get install ffmpeg
scripts/cameras/start.sh         # downloads MediaMTX, builds the demo-room clip, serves the cameras
npm start                        # in another terminal: API on :8000, dashboard on :5173
.venv/bin/python scripts/cameras/connect_demo.py   # cam-01 daycare, cam-02 bourbon, cam-03 timessquare
```

Or in the dashboard: Settings → Manage source → `rtsp://127.0.0.1:8554/daycare`, then the **Add a camera** tile (Focus or
Grid layout) for the others. Watch any camera in a browser at `http://127.0.0.1:8888/<path>` (MediaMTX's HLS player).

## Cameras in `mediamtx.yml`

| Path | What | Kind | Use it for |
|---|---|---|---|
| `daycare` | GMDCSA24 Subject 1: one adult in a home room, everyday movement, then a fall (38 s loop, 960×540, 15 fps) | **Recorded, staged, looped.** Never present as live or as a daycare | Repeatable fall / stillness / zone tests; the demo's incident |
| `bourbon` | EarthCam, Bourbon Street (New Orleans) from a balcony | Public live webcam, relayed | People at a CCTV angle, shop entrances below, daytime US |
| `timessquare` | EarthCam, Times Square TKTS steps | Public live webcam, relayed | Crowd transport/load test; people are small |
| `dublin` | EarthCam, Temple Bar (Dublin), on demand | Public live webcam, relayed | Busy street at night (US daytime = Dublin evening) |
| anything else | Publish from a phone, OBS or ffmpeg to `rtsp://<laptop>:8554/<name>` | Live | Staged scenes with consenting teammates |

Public relays run `relay_public.sh`: streamlink resolves the webcam page to its current tokenized HLS URL, ffmpeg copies the
H.264 video into MediaMTX (`-re` paces HLS segment bursts back to real time, so SRC-4 never sees burst-then-gap and marks
the camera offline). MediaMTX restarts the relay when it exits, so expired tokens are re-resolved.

**Rights.** Only cameras their publisher intends the public to watch (EarthCam, operator-run YouTube channels, city DOT
cameras). Never unsecured private cameras (insecam, camhacker and similar), never footage of identifiable children. EarthCam
content is EarthCam's: fine for private development and a hackathon demo on your screen with their logo visible; do not
record, redistribute or rebroadcast it, and say "courtesy of EarthCam" if it appears in a demo.

## Your own cameras

| Device | URL for the API (`camera`) | Notes |
|---|---|---|
| Android, IP Webcam | `http://PHONE:8080/video` (MJPEG) or `rtsp://PHONE:8080/h264_ulaw.sdp` | Same Wi-Fi. MJPEG is simplest; RTSP saves bandwidth |
| Android, DroidCam | `http://PHONE:4747/video` | One client at a time |
| iPhone, IP Camera Lite / IP4K / OctoStream | the `rtsp://PHONE…` URL the app shows | Or push: Larix Broadcaster / IP Camera Lite → `rtmp://LAPTOP:1935/phone` or `srt://LAPTOP:8890?streamid=publish:phone`, then use `rtsp://127.0.0.1:8554/phone` |
| Any phone browser | open `http://LAPTOP:8889/phone/publish` (WebRTC) | Browsers allow the camera only on HTTPS or localhost; configure MediaMTX TLS or use a USB-tethered phone |
| Tapo C1xx/C2xx | `rtsp://USER:PASS@IP:554/stream2` (`stream1` = full res) | Create a Camera Account in the Tapo app first |
| Reolink | `rtsp://USER:PASS@IP:554/h264Preview_01_sub` (`_main`) | Enable RTSP in settings on newer firmware |
| Amcrest / Dahua / Lorex | `rtsp://USER:PASS@IP:554/cam/realmonitor?channel=1&subtype=1` | `subtype=0` main |
| Hikvision | `rtsp://USER:PASS@IP:554/Streaming/Channels/102` | `101` main |
| Wyze v3 / Pan v3 | `rtsp://USER:PASS@IP/stream0` (beta RTSP firmware) | Wyze's RTSP firmware is beta and has been withdrawn before |

Prefer the camera's **substream** (360p–720p): pose runs on 640 px wide frames anyway, and decoding a 1080p30 main stream
costs CPU for nothing. To share one camera between NestWatch and a viewer, proxy it through MediaMTX
(`paths: front: {source: rtsp://…}`) and read `rtsp://127.0.0.1:8554/front`.

## Building the demo room

`make_demo_room.py` downloads five GMDCSA24 clips (Alam et al. 2024, MIT on GitHub, CC BY 4.0 on Zenodo,
doi:10.5281/zenodo.12921216) and concatenates them with ffmpeg: walking and everyday movement, then a fall. It is the
team's spacetime-vision demo room, rebuilt with ffmpeg so it is H.264 with a 1 s keyframe interval (loops with `-c copy`,
readers start within a second). For more variety, CAUCAFall (Mendeley, CC BY 4.0) is filmed from a ceiling-corner
Hikvision CCTV camera, the angle closest to a real installation.

## YouTube live cameras (works on laptops, not in the Mana sandbox)

Many operator-run webcams (restaurants, gas-station car washes, shops) are YouTube live streams. The same relay works for
them on a home or venue connection:

```yaml
  schooner:   # in mediamtx.yml paths:
    runOnDemand: bash scripts/cameras/relay_public.sh https://www.youtube.com/watch?v=tBP1K0VbN6U
    runOnDemandRestart: yes
    runOnDemandStartTimeout: 20s
```

From datacenter IPs YouTube serves the playlist but refuses the video segments (403), and via VPN exits it asks to sign in;
that is what happened in the Mana sandbox on 2026-10-24. Do not work around it with someone else's cookies.
