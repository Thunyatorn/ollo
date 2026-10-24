"""Connect the development cameras to a running NestWatch API (SRC-4 + SRC-5) and start analysis.

    .venv/bin/python scripts/cameras/connect_demo.py                       # daycare + bourbon + timessquare
    .venv/bin/python scripts/cameras/connect_demo.py --api http://127.0.0.1:8000 \
        "rtsp://127.0.0.1:8554/daycare=Toddler room (simulated, recorded)" "rtsp://192.168.1.40:8080/h264_ulaw.sdp=Front door (phone)"

Run it on the API's machine: the operator session is bootstrapped from loopback only (PRV-2). The first
camera becomes cam-01 (it resets the session); the rest are added with POST /api/cameras. It then prints
each camera's delivered and analyzed frame rates for --watch seconds.
"""
import argparse
import sys
import time

import httpx

DEFAULT = ['rtsp://127.0.0.1:8554/daycare=Toddler room (simulated, recorded)',
           'rtsp://127.0.0.1:8554/bourbon=Bourbon St balcony (public live)',
           'rtsp://127.0.0.1:8554/timessquare=Times Square plaza (public live)']


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cameras', nargs='*', default=DEFAULT, help='URL=Room name, at most 4')
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--watch', type=int, default=30, help='seconds to print rates for (0 to skip)')
    args = parser.parse_args()
    specs = [(c.split('=', 1) + [''])[:2] for c in args.cameras]
    with httpx.Client(base_url=args.api, timeout=30) as api:
        api.get('/api/state').raise_for_status()  # Loopback bootstrap sets the session cookie.

        def call(method, path, body=None):
            r = api.request(method, path, json=body)
            if r.status_code >= 300:
                sys.exit(f'{method} {path}: {r.status_code} {r.text[:300]}')
            return r.json()
        (first, room), rest = specs[0], specs[1:]
        call('POST', '/api/source', {'source_type': 'server_camera', 'camera': first})
        if room:
            call('PUT', '/api/settings', {'room_label': room})
        call('POST', '/api/session/start')
        for url, room in rest:
            call('POST', '/api/cameras', {'camera': url, 'room_label': room or None})
        end = time.time() + args.watch
        while time.time() < end:
            time.sleep(5)
            line = ' | '.join(f"{c['id']} {c['health']} {c['capture']['camera_fps'] if c['capture'] else 0:.0f}→{c['analysis_fps']:.1f} fps {c['people']}p"
                              for c in call('GET', '/api/cameras')['cameras'])
            print(line, flush=True)


if __name__ == '__main__':
    main()
