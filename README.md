# NestWatch (local development)

Spec: `CLUADE.md`. Build plan: see the plan file in `~/.claude/plans/`.

## Run it locally

You need Node, pnpm and the Spacetime CLI (`spacetime`).

```bash
pnpm install

# 1. database server (keep running)
spacetime start --data-dir ./.stdb

# 2. publish the module and generate the browser/tool bindings
cd spacetime
spacetime publish nestwatch-test --server local --module-path spacetimedb --delete-data=always --yes --no-config
spacetime generate --lang typescript --out-dir ../web/src/module_bindings --module-path spacetimedb --no-config
cd ..

# 3. fake vision: run once to learn its identity, then seed with that identity
cd tools && pnpm fake-vision        # prints "connected as <hex>", then exits with "No room"
cd .. && VISION_ID=<hex> ./scripts/seed-local.sh

# 4. run the fake vision and the web app (separate terminals)
cd tools && pnpm fake-vision        # keys: e = event, u = unsupervised, b = buzzer tap
cd web && pnpm dev                  # http://localhost:5173 (also on your LAN address, for the phone)
```

Sign in as **Maria** (code `maria`, primary) or **Bob** (code `bob`, backup).
The phone app is the same site: open `/m/alert` on your phone (same Wi-Fi), or use "Phone view" in the sidebar.

## Vision service (real camera or video)

Needs the local server running and the database seeded (steps above). The fake vision and the real one both write positions to the same room, so run only one.

```bash
cd vision
# 1. calibrate: put 6 taped markers on the floor, measure them, click them in the picture in the same order
.venv/bin/python scripts/calibrate.py 0 --floor "0,0;4,0;4,3;0,3;2,0;2,3"        # 0 = webcam; or a video file, or an rtsp/http URL
# 2. run it
.venv/bin/python -m nestwatch_vision.main 0
# no camera calibrated yet? a video, with the picture stretched over the room (positions are not real):
.venv/bin/python -m nestwatch_vision.main out/pan_long.mp4 --demo-map --realtime
# see the skeletons and timing without sending anything
.venv/bin/python scripts/live_pose.py 0
```

Clips and key frames are written to `vision/evidence/` (blurred, H.264, deleted after 7 days). Recording needs the face detector model `weights/face_detection_yunet_2023mar.onnx`
(from `https://github.com/opencv/opencv_zoo`); without it the service refuses to record rather than save unblurred video. Use `--no-evidence` to run without saving clips.

## Tests

`cd vision && .venv/bin/python -m pytest` runs the vision tests (about 15 s). `spacetime/scripts/test-local.sh` checks the role rules and the alert state machine against a local server
(see the header of the script for the setup it needs). It takes about a minute because it waits for the real escalation timers.

## Layout

| Folder | What |
| --- | --- |
| `spacetime/` | Spacetime module (tables, reducers, escalation timer) |
| `web/` | Dashboard (`/`) and phone app (`/m/*`) |
| `tools/` | Fake vision service for testing without a camera |
| `packages/shared/` | Shared message types |
| `vision/` | The vision service (math in `MATH.md`) |
| `weights/` | Pose model files (not in git) |
| `worker/`, `firmware/` | Not built yet |
