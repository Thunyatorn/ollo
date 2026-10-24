# Recording footage to tune Ollo (M9)

The detectors were tuned on simulations and on adults in public datasets. Their thresholds are only as good as the
footage they are checked against, so the last step is your own room, your camera, and (with consent) people moving the
way children do. This guide gives you clips the evaluation tool can score without any extra work.

## Before recording

1. **Camera:** mount it where it will really be, high on a wall looking down at the floor. Do not move it afterwards;
   if it moves, calibrate again.
2. **Floor markers:** put 6 pieces of tape on the floor: the 4 corners of the area you care about and 2 more in the
   middle of two opposite edges. Measure each from the room's top-left corner in meters (x to the right, y down), and
   write them down. Leave the tape in place while recording.
3. **Calibrate** once: `scripts/calibrate.py 0 --floor "0,0;4,0;4,3;0,3;2,0;2,3"` (your own numbers). Keep the
   printed `calibration_cam1.json`; its points go into the labels file below.
4. **Consent:** everyone filmed must agree. Do not film children without their parents' written consent. Adults acting
   (crouching, crawling, sitting on the floor) are a reasonable stand-in for a first pass.

## What to record (each clip 10 to 30 seconds, start the recording before the action)

| Clip type | How many | What happens | Label it |
| --- | --- | --- | --- |
| Walk at the restricted zone | 10 | Walk toward the zone at different speeds and angles and step in | `zone_entry` at the moment a foot crosses the tape |
| Near but not in | 10 | Walk past it, stop 0.5 to 1 m short, play beside it | no events (a negative clip) |
| Fall | 10 | Fall onto a mat: forward, sideways, from sitting, from kneeling | `fall` at the moment the fall starts |
| Fall look-alikes | 10 | Sit down hard, lie down on purpose, crawl, pick something up | no events |
| Alone | 5 | One person tagged as the adult leaves the room for 20 s | `unsupervised` at the moment the adult leaves |
| Ordinary play | 5 | Several people moving normally for a minute | no events |

Record a few clips in poor light and with people partly hidden by furniture: that is where detectors fail.

## The labels file

Put the clips in `vision/clips/` (git ignores video files) and write `vision/clips/labels.json`:

```json
{"clips": [
  {"path": "fall_01.mp4", "split": "tune",
   "events": [{"kind": "fall", "onset_s": 4.2}],
   "calibration": {"image_points": [[112, 640], [1180, 655], [1010, 300], [260, 290], [646, 650], [635, 296]],
                   "floor_points": [[0, 0], [4, 0], [4, 3], [0, 3], [2, 0], [2, 3]]},
   "zones": [{"id": "z_1", "name": "Stairs", "severity": "high", "status": "active",
              "polygon": [{"x": 2.8, "y": 1.9}, {"x": 4, "y": 1.9}, {"x": 4, "y": 3}, {"x": 2.8, "y": 3}]}]},
  {"path": "sit_hard_01.mp4", "split": "test", "events": [], "calibration": {"...": "same as above"}}
]}
```

Use `"split": "tune"` for about two thirds of the clips and `"test"` for the rest, chosen **before** looking at any
results, and never tune on `test`.

## Running it

```bash
cd vision
.venv/bin/python scripts/eval_clips.py clips/labels.json --split test               # how it does now
.venv/bin/python scripts/eval_clips.py clips/labels.json --tune "cusum_h=0.15,0.2,0.3 fall.hold_s=0.5,0.8,1.2 fall.drop_frac=0.35,0.45"
```

The second command picks the best setting on `tune` and reports it on `test`. Put the chosen values into
`nestwatch_vision/config.py` (or `detectors/fall.py`) and record the test numbers in MATH.md section 14.
