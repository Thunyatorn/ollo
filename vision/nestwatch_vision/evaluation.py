"""Scoring for labelled clips, matching the team's server/evaluate.py rules so numbers are comparable:
a hit is an alert of the right kind 0-5 s after a labelled onset (one-to-one); every other alert of that kind is a false
alarm; intervals are Wilson 95%; false alarms per hour are counted on clips with no labelled event."""
import math

HIT_WINDOW_S = 5.0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p, denom = k / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def score(clips: list[dict]) -> dict:
    """clips: [{"events": [{"kind", "onset_s"}], "alerts": [{"kind", "t_s"}], "duration_s"}]"""
    kinds = sorted({e["kind"] for c in clips for e in c["events"]} | {a["kind"] for c in clips for a in c["alerts"]})
    negative_hours = sum(c["duration_s"] for c in clips if not c["events"]) / 3600
    out = {}
    for kind in kinds:
        tp = fn = fp = neg_fp = 0
        delays = []
        for c in clips:
            alerts = sorted(a["t_s"] for a in c["alerts"] if a["kind"] == kind)
            used = set()
            for onset in sorted(e["onset_s"] for e in c["events"] if e["kind"] == kind):
                m = next((i for i, t in enumerate(alerts) if i not in used and onset <= t <= onset + HIT_WINDOW_S), None)
                if m is None:
                    fn += 1
                else:
                    used.add(m); tp += 1; delays.append(alerts[m] - onset)
            extra = len(alerts) - len(used)
            fp += extra
            if not c["events"]:
                neg_fp += extra
        out[kind] = {"tp": tp, "fn": fn, "fp": fp,
                     "precision": tp / (tp + fp) if tp + fp else None, "precision_ci": wilson(tp, tp + fp),
                     "recall": tp / (tp + fn) if tp + fn else None, "recall_ci": wilson(tp, tp + fn),
                     "mean_delay_s": sum(delays) / len(delays) if delays else None,
                     "false_alarms_per_hour": neg_fp / negative_hours if negative_hours else None}
    return out
