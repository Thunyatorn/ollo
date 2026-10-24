"""Build a looping "demo room" video for a simulated CCTV camera (scripts/cameras/README.md).

    .venv/bin/python scripts/cameras/make_demo_room.py            # → scripts/cameras/media/demo_room.mp4

One fixed indoor camera, one person moving about, then a fall near the end: the same plan as the
team's spacetime-vision demo room. Clips are Subject 1 of GMDCSA24 (Alam et al., MIT licence on
GitHub, CC BY 4.0 on Zenodo, doi:10.5281/zenodo.12921216), downloaded once and cached. Staged by
consenting adult actors; never present it as daycare footage or as accuracy evidence.

The output is H.264 with a keyframe every second, so MediaMTX can loop it with `-c copy` (no
re-encoding) and a reconnecting reader starts within a second.
"""
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEDIA = HERE / 'media'
BASE = 'https://raw.githubusercontent.com/ekramalam/GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos/master/'
PLAN = ['Subject 1/ADL/08.mp4', 'Subject 1/ADL/05.mp4', 'Subject 1/ADL/11.mp4', 'Subject 1/ADL/02.mp4', 'Subject 1/Fall/04.mp4']
FPS, WIDTH, HEIGHT = 15, 960, 540


def fetch(name: str) -> Path:
    target = MEDIA / 'gmdcsa24' / name.replace('Subject 1/', 's1_').replace('/', '_')
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f'downloading {name}')
        with urllib.request.urlopen(BASE + urllib.parse.quote(name), timeout=60) as response, open(target, 'wb') as out:
            shutil.copyfileobj(response, out)
    return target


def main():
    if not shutil.which('ffmpeg'):
        sys.exit('ffmpeg is required (brew install ffmpeg / sudo apt-get install ffmpeg)')
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else MEDIA / 'demo_room.mp4'
    out.parent.mkdir(parents=True, exist_ok=True)
    clips = [fetch(name) for name in PLAN]
    inputs = [arg for clip in clips for arg in ('-i', str(clip))]
    scaled = ''.join(f'[{i}:v]fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:-1:-1,setsar=1[v{i}];' for i in range(len(clips)))
    graph = scaled + ''.join(f'[v{i}]' for i in range(len(clips))) + f'concat=n={len(clips)}:v=1:a=0[out]'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', graph, '-map', '[out]', '-c:v', 'libx264', '-preset', 'veryfast',
                    '-crf', '23', '-pix_fmt', 'yuv420p', '-g', str(FPS), '-keyint_min', str(FPS), '-sc_threshold', '0', '-movflags', '+faststart', str(out)], check=True)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(out)], capture_output=True, text=True)
    print(f'wrote {out}: {float(probe.stdout.strip()):.1f} s, {WIDTH}x{HEIGHT} at {FPS} fps (fall in the last clip)')


if __name__ == '__main__':
    main()
