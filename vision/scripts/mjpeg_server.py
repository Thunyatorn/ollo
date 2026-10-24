"""Serve a video file as a network camera (MJPEG over HTTP), looping, for testing live-camera behaviour.

  .venv/bin/python scripts/mjpeg_server.py out/pan_long.mp4 [--port 8090] [--drop-at 20 --drop-for 10]
  then:  .venv/bin/python -m nestwatch_vision.main http://127.0.0.1:8090/video.mjpg ...
--drop-at/--drop-for stop the stream (and refuse connections) for a while, like an unplugged camera.
"""
import argparse
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("--port", type=int, default=8090)
ap.add_argument("--fps", type=float, default=15)
ap.add_argument("--drop-at", type=float, default=0)
ap.add_argument("--drop-for", type=float, default=0)
a = ap.parse_args()
t0 = time.time()


def dropped() -> bool:
    return bool(a.drop_for) and a.drop_at <= time.time() - t0 < a.drop_at + a.drop_for


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if dropped():
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        cap = cv2.VideoCapture(a.video)
        try:
            while True:
                if dropped():
                    return                                        # the camera "unplugs": the connection just ends
                ok, img = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                time.sleep(1 / a.fps)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            cap.release()


def announce():
    if a.drop_for:
        time.sleep(a.drop_at)
        print(f"{time.strftime('%T')} camera unplugged for {a.drop_for:.0f} s", flush=True)
        time.sleep(a.drop_for)
        print(f"{time.strftime('%T')} camera plugged back in", flush=True)


threading.Thread(target=announce, daemon=True).start()
print(f"serving {a.video} at http://127.0.0.1:{a.port}/video.mjpg", flush=True)
ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
