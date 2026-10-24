"""EVAL-1 harness: Wilson intervals, event matching, and the offline engine on real video files."""
import json

import cv2
import numpy as np
import pytest
from server.evaluate import evaluate, score, wilson


def test_wilson_interval_known_values():
    low, high = wilson(8, 10)
    assert low == pytest.approx(0.490, abs=0.002) and high == pytest.approx(0.943, abs=0.002)
    assert wilson(0, 0) == (0.0, 1.0)  # No data: no claim.
    assert wilson(5, 5)[0] < 1.0 and wilson(5, 5)[1] == pytest.approx(1.0)


def test_matching_counts_hits_misses_and_false_alarms():
    clips = [
        {'name': 'a', 'duration_s': 30, 'events': [{'kind': 'fall', 'onset_s': 3.0}], 'alerts': [{'kind': 'fall', 't_s': 4.0}, {'kind': 'fall', 't_s': 20.0}]},
        {'name': 'b', 'duration_s': 30, 'events': [{'kind': 'distress', 'onset_s': 2.0}], 'alerts': [{'kind': 'distress', 't_s': 8.0}]},
        {'name': 'c', 'duration_s': 60, 'events': [], 'alerts': [{'kind': 'rhythmic', 't_s': 10.0}]},
        {'name': 'd', 'duration_s': 30, 'events': [{'kind': 'fall', 'onset_s': 5.0}], 'alerts': [{'kind': 'fall', 't_s': 4.0}]},  # Before onset: not a hit.
    ]
    report = score(clips)
    fall, distress, rhythmic = report['fall'], report['distress'], report['rhythmic']
    assert (fall['tp'], fall['fn'], fall['fp']) == (1, 1, 2) and fall['mean_delay_s'] == pytest.approx(1.0)
    assert fall['recall'] == pytest.approx(0.5) and fall['precision'] == pytest.approx(1 / 3)
    assert (distress['tp'], distress['fn'], distress['fp']) == (0, 1, 1)  # 6 s late is outside the 5 s window.
    assert rhythmic['false_alarms_per_hour'] == pytest.approx(60.0) and rhythmic['recall'] is None


def test_runs_engine_on_video_files(tmp_path, monkeypatch):
    monkeypatch.setenv('LOOKOUT_DETECTOR', 'hog')  # Fast and deterministic; this checks the pipeline, not accuracy.
    path = tmp_path / 'empty.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 30, (320, 240))
    for i in range(90):
        writer.write(np.full((240, 320, 3), 40 + i % 20, dtype=np.uint8))
    writer.release()
    labels = tmp_path / 'labels.json'
    labels.write_text(json.dumps({'clips': [{'path': 'empty.avi', 'split': 'test', 'events': []}]}))
    result = evaluate(labels, split='test')
    clip = result['clips'][0]
    assert clip['frames_analyzed'] == pytest.approx(36, abs=1) and clip['duration_s'] == pytest.approx(3.0, abs=0.1)
    assert clip['alerts'] == [] and result['negative_hours'] == pytest.approx(3 / 3600, rel=0.05)
    assert 'not deployment accuracy' in result['markdown'] and 'split: test' in result['markdown']
    assert evaluate(labels, split='tune')['clips'] == []
