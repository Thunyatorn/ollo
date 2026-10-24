"""A phone as the camera.

The phone opens https://<laptop>:8443/phone-cam in its browser, allows the camera, and posts JPEG frames to the vision
service over the daycare Wi-Fi. The video goes from the phone to this laptop and nowhere else: no tunnel, no cloud.

  * Phones only give a web page the camera over https, so the laptop makes its own self-signed certificate
    (the phone shows a warning once; accept it).
  * Anyone on the Wi-Fi could otherwise send fake frames (for example an empty room), so frames are accepted only with
    the pairing code that is printed on the laptop and carried in the page address.
  * The frames feed the same pipeline as any camera. `PhoneFeed` looks like an OpenCV capture, so LiveSource's
    "newest frame only", offline notice and reconnect logic apply unchanged.
"""
import ipaddress
import logging
import os
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .local_api import PrivateNetworkOnly

log = logging.getLogger("nestwatch.phonecam")
MAX_FRAME_BYTES = 1_500_000
PAGE = os.path.join(os.path.dirname(__file__), "static", "phonecam.html")


class PhoneFeed:
    """Quacks like cv2.VideoCapture for LiveSource: read() waits for the next frame, release() does nothing
    (a quiet phone is not a closed device; the same feed is reused when frames resume)."""

    def __init__(self):
        self._cv = threading.Condition()
        self._img: np.ndarray | None = None
        self._seq = self._read_seq = 0
        self.received = self.stale = 0
        self.last_push = 0.0
        self._session, self._last_in = "", 0

    def push(self, img: np.ndarray, session: str = "", seq: int = 0) -> bool:
        """Keep `img` as the newest frame. The phone sends several frames at once, so a frame that arrives after a
        NEWER one from the same page session is dropped (False): old pictures must never replace new ones."""
        with self._cv:
            if session and session == self._session and seq and seq <= self._last_in:
                self.stale += 1
                return False
            if session:
                self._session, self._last_in = session, max(seq, self._last_in if session == self._session else 0)
            self._img, self._seq = img, self._seq + 1
            self.received += 1
            self.last_push = time.perf_counter()
            self._cv.notify_all()
            return True

    def read(self, timeout: float = 1.0):
        with self._cv:
            if not self._cv.wait_for(lambda: self._seq != self._read_seq, timeout):
                return False, None
            self._read_seq = self._seq
            return True, self._img

    def release(self) -> None:
        pass


def create_phone_app(feed: PhoneFeed, code: str) -> FastAPI:
    app = FastAPI(title="NestWatch phone camera", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/phone-cam")
    def page():
        with open(PAGE, encoding="utf-8") as f:
            return HTMLResponse(f.read(), headers={"Cache-Control": "no-store"})

    @app.post("/phone-frame")
    async def frame(request: Request):
        if not secrets.compare_digest(request.headers.get("x-pair-code", ""), code):
            raise HTTPException(403, "wrong pairing code")                      # checked before reading the body
        if int(request.headers.get("content-length") or 0) > MAX_FRAME_BYTES:
            raise HTTPException(413, "frame too large")
        body = await request.body()
        if len(body) > MAX_FRAME_BYTES or not body.startswith(b"\xff\xd8"):
            raise HTTPException(400, "send one JPEG frame")
        img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "could not read that JPEG")
        try:
            seq = int(request.headers.get("x-frame-seq") or 0)
        except ValueError:
            seq = 0
        feed.push(img, request.headers.get("x-session", "")[:32], seq)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    return app


def lan_ips() -> list[str]:
    """This computer's address(es) on the local network, for the page address and the certificate."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))                                        # no packet is sent; it just picks the route
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    return [ip for ip in dict.fromkeys(found) if not ip.startswith("127.")]


def ensure_cert(directory: str, ips: list[str]) -> tuple[str, str]:
    """A self-signed certificate valid for localhost and `ips`, reused until an address is missing or it nears its end."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    os.makedirs(directory, exist_ok=True)
    cert_path, key_path = os.path.join(directory, "phonecam.pem"), os.path.join(directory, "phonecam.key")
    want = {"127.0.0.1", *ips}
    if os.path.exists(cert_path) and os.path.exists(key_path):
        try:
            cert = x509.load_pem_x509_certificate(open(cert_path, "rb").read())
            have = {str(i) for i in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)}
            if want <= have and cert.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=30):
                return cert_path, key_path
        except Exception:
            pass                                                               # unreadable: make a new one
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NestWatch phone camera")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), *[x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(want)]]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


def serve_phone_camera(feed: PhoneFeed, code: str, port: int, cert_dir: str, insecure: bool = False):
    """Start the phone-camera server on its own thread. Returns (server, page addresses to open on the phone).
    insecure=True serves plain http, for testing on THIS laptop only (a phone will refuse the camera over http)."""
    app = PrivateNetworkOnly(create_phone_app(feed, code))
    ips = lan_ips()
    if insecure:
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        urls = [f"http://127.0.0.1:{port}/phone-cam?code={code}"]
    else:
        cert, key = ensure_cert(cert_dir, ips)
        config = uvicorn.Config(app, host="0.0.0.0", port=port, ssl_certfile=cert, ssl_keyfile=key, log_level="warning")
        urls = [f"https://{ip}:{port}/phone-cam?code={code}" for ip in ips] or [f"https://127.0.0.1:{port}/phone-cam?code={code}"]
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="phonecam").start()
    return server, urls
