# Using a phone as the camera

The phone's browser is the camera. It sends frames over the daycare Wi-Fi to the vision service on the laptop. The
video goes phone to laptop only: no cloud, no tunnel. Blurring and clips work exactly as for a webcam.

## Steps

1. Put the phone and the laptop on the same Wi-Fi.
2. On the laptop, start the vision service with the source `phone`:
   ```bash
   cd vision
   .venv/bin/python -m nestwatch_vision.main phone --worker-url http://127.0.0.1:8787
   ```
   It prints a line like `PHONE CAMERA: open https://10.0.8.40:8443/phone-cam?code=Ab3dEf on the phone` and waits.
   macOS may ask whether Python may accept incoming connections: allow it.
3. Type that address into the phone's browser (the whole thing, including `?code=...`).
4. The browser warns that the certificate is not trusted (the laptop made it itself). Accept it once:
   Chrome on Android: Advanced, then Proceed. Safari on iPhone: Show Details, then visit this website.
5. Tap **Start camera** and allow the camera. The page shows the frame rate it is sending. The laptop starts
   detecting as soon as the first frame arrives.
6. Mount the phone where it sees the whole room, plug it in, and keep the page open with the screen on
   (the page asks the phone not to sleep, but a locked phone stops sending).
7. **Calibrate again** in Setup (a phone's picture has a different size and view from the webcam), and do not move
   the phone afterwards: moving it makes every position wrong until you recalibrate.

## Good to know

- **Picture size adapts:** the page sends 640 px wide frames (the size the model reads) and shrinks them down to 320 px
  by itself when the Wi-Fi is slow, then grows them again. The page shows the frame rate, size and time per frame.
- **Keep the page in front:** a page in a background tab, or on a locked phone, can slow down or stop. The page times
  its frames from a worker thread so a background tab keeps going, but a locked phone will still stop sending.
- **Laptop webcam:** you don't need this page for the laptop's own camera; use `main.py 0` instead. Opening the page on
  the laptop also works (it then uses the laptop's camera) and is a handy way to check the page itself.
- **No positions yet?** `0 tracks` means the camera isn't calibrated: calibrate in Setup, or add `--demo-map` for a
  quick look that stretches the picture over the room (positions are then not real).

- **Pairing code:** frames are accepted only with the code printed on the laptop, so another device on the Wi-Fi cannot
  feed in a fake picture. A new code is made each run; pass `--phone-code` to keep one.
- **Phone goes quiet** (locked, Wi-Fi drop, page closed): the camera shows offline on the dashboard, the primary's buzzer
  gets one notice, and everything resumes by itself when frames return.
- **Certificate:** kept in `vision/certs/` (git-ignored) and reused until the laptop's address changes.
- **Different port:** `--phone-port 9443`.
- **Testing without a phone:** `scripts/phone_sim.py VIDEO --code CODE` posts a video's frames the way the page does;
  `--phone-http` serves plain http on this laptop only, so a desktop browser can open the page.

## Tested and not tested

Tested: the server, the pairing code, the certificate, an offline and back cycle, and the page's own code in Chrome
with a stand-in camera. Not tested: a real phone. The usual risks are the certificate warning steps above and
iPhones pausing the page when the screen locks.
