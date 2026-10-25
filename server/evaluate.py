"""EVAL-1: run the real engine offline on labeled staged clips and report per-kind accuracy.

Usage: npm run eval -- labels.json [--split test] [--out results]

labels.json: {"clips": [{"path": "fall_01.mp4", "split": "test", "settings": {...},
               "events": [{"kind": "fall", "onset_s": 3.2}]}]}
Paths are relative to the label file. A clip with no events is a negative clip.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
from pathlib import Path

HIT_WINDOW_S = 5.0
SAMPLE_FPS = 12.0
ALERT_KINDS = ('boundary', 'approach', 'distress', 'fall', 'rhythmic', 'stillness')


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials; (0, 1) when there is no data."""
    if n == 0:
        return 0.0, 1.0
    p, denom = k / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def score(clips: list[dict]) -> dict:
    """Per kind: hits within 0–5 s after onset (one-to-one), misses, false alarms, intervals, delay, FA/hour."""
    kinds = sorted({e['kind'] for c in clips for e in c['events']} | {a['kind'] for c in clips for a in c['alerts']})
    negative_hours = sum(c['duration_s'] for c in clips if not c['events']) / 3600
    report = {}
    for kind in kinds:
        tp = fn = fp = negative_fp = 0
        delays = []
        for clip in clips:
            alerts = sorted(a['t_s'] for a in clip['alerts'] if a['kind'] == kind)
            used = set()
            for onset in sorted(e['onset_s'] for e in clip['events'] if e['kind'] == kind):
                match = next((i for i, t in enumerate(alerts) if i not in used and onset <= t <= onset + HIT_WINDOW_S), None)
                if match is None:
                    fn += 1
                else:
                    used.add(match)
                    tp += 1
                    delays.append(alerts[match] - onset)
            extra = len(alerts) - len(used)
            fp += extra
            if not clip['events']:
                negative_fp += extra
        report[kind] = {
            'tp': tp, 'fn': fn, 'fp': fp,
            'precision': tp / (tp + fp) if tp + fp else None, 'precision_ci': wilson(tp, tp + fp),
            'recall': tp / (tp + fn) if tp + fn else None, 'recall_ci': wilson(tp, tp + fn),
            'mean_delay_s': sum(delays) / len(delays) if delays else None,
            'false_alarms_per_hour': negative_fp / negative_hours if negative_hours else None,
        }
    return report


async def run_clip(engine, path: Path, settings: dict) -> dict:
    """Sample the clip at 12 fps, encode like the dashboard, and run the engine on the clip's own timeline."""
    import cv2
    engine.configure(settings)
    capture = cv2.VideoCapture(str(path))
    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    alerts, index, sampled, next_t = [], 0, 0, 0.0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        t = index / source_fps
        index += 1
        if t + 1e-6 < next_t:
            continue
        next_t += 1 / SAMPLE_FPS
        if frame.shape[1] != 640:
            frame = cv2.resize(frame, (640, round(640 * frame.shape[0] / frame.shape[1])))
        jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])[1].tobytes()
        result = await engine.process_frame({'session_id': 'eval', 'epoch': 1, 'frame_seq': sampled, 'media_time_ms': t * 1000, 'image': base64.b64encode(jpeg).decode()})
        sampled += 1
        alerts += [{'kind': o['kind'], 't_s': round(t, 3)} for o in result.get('observations', []) if o.get('kind') in ALERT_KINDS]
    capture.release()
    return {'frames_analyzed': sampled, 'duration_s': round(index / source_fps, 3), 'alerts': alerts}


def markdown(report: dict, clips: list[dict], split: str | None, negative_hours: float) -> str:
    fmt = lambda v, ci=None: '—' if v is None else f'{v:.0%}' + (f' ({ci[0]:.0%}–{ci[1]:.0%})' if ci else '')
    negatives = sum(1 for c in clips if not c['events'])
    lines = [f"# ollo evaluation · split: {split or 'all'}", '',
             f'{len(clips)} staged clips ({negatives} negative, {negative_hours * 60:.1f} min of negative footage). '
             'Staged clips measure this prototype on this footage; they are not deployment accuracy.', '',
             '| Kind | Hits | Missed | False alarms | Precision (95% CI) | Recall (95% CI) | Mean delay | False alarms / hour |',
             '|---|---|---|---|---|---|---|---|']
    for kind, r in report.items():
        delay = '—' if r['mean_delay_s'] is None else f"{r['mean_delay_s']:.1f} s"
        rate = '—' if r['false_alarms_per_hour'] is None else f"{r['false_alarms_per_hour']:.1f}"
        lines.append(f"| {kind} | {r['tp']} | {r['fn']} | {r['fp']} | {fmt(r['precision'], r['precision_ci'])} | {fmt(r['recall'], r['recall_ci'])} | {delay} | {rate} |")
    return '\n'.join(lines) + '\n'


def evaluate(labels_path, split: str | None = None) -> dict:
    from .vision import VisionEngine
    labels_path = Path(labels_path)
    entries = [c for c in json.loads(labels_path.read_text())['clips'] if split is None or c.get('split', 'test') == split]
    engine = VisionEngine()
    engine.warm()
    clips = []
    for entry in entries:
        path = (labels_path.parent / entry['path']).resolve()
        run = asyncio.run(run_clip(engine, path, entry.get('settings', {})))
        clips.append({'name': entry['path'], 'split': entry.get('split', 'test'), 'events': entry.get('events', []), **run})
    report = score(clips)
    negative_hours = sum(c['duration_s'] for c in clips if not c['events']) / 3600
    return {'split': split, 'clips': clips, 'report': report, 'negative_hours': negative_hours, 'markdown': markdown(report, clips, split, negative_hours)}


def main():
    parser = argparse.ArgumentParser(description='Run ollo detection offline on labeled clips.')
    parser.add_argument('labels')
    parser.add_argument('--split', choices=['tune', 'test'])
    parser.add_argument('--out', default=None, help='Directory for eval.json and eval.md (default: next to the label file)')
    args = parser.parse_args()
    result = evaluate(args.labels, args.split)
    out = Path(args.out) if args.out else Path(args.labels).parent
    out.mkdir(parents=True, exist_ok=True)
    (out / 'eval.json').write_text(json.dumps({k: v for k, v in result.items() if k != 'markdown'}, indent=2))
    (out / 'eval.md').write_text(result['markdown'])
    print(result['markdown'])


if __name__ == '__main__':
    main()
