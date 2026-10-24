import time
from nestwatch_vision.alarm import AlarmPlayer


def make():
    n = {"c": 0}

    def play():
        n["c"] += 1
        time.sleep(0.01)
    return AlarmPlayer(play_once=play, gap_s=0.01), n


def test_silent_until_started_then_plays_until_every_reason_is_cleared():
    a, n = make()
    time.sleep(0.15)
    assert n["c"] == 0 and not a.active
    a.start("unanswered:a_1")
    a.start("offline:evt_9", duration_s=30)
    time.sleep(0.15)
    assert a.active and n["c"] > 3
    a.stop("unanswered:a_1")
    assert a.active                                                    # a second reason is still holding it on
    a.stop("offline:evt_9")
    time.sleep(0.1)
    c = n["c"]
    time.sleep(0.15)
    assert not a.active and n["c"] == c                                # really silent
    a.close()


def test_a_timed_reason_ends_by_itself():
    a, n = make()
    a.start("offline:evt_1", duration_s=0.12)
    time.sleep(0.05)
    assert a.active
    time.sleep(0.3)
    assert not a.active and a.reasons() == []
    a.close()


def test_a_failing_sound_does_not_kill_the_alarm_thread():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("no audio device")
    a = AlarmPlayer(play_once=flaky, gap_s=0.01)
    a.start("x")
    time.sleep(1.4)
    assert calls["n"] >= 2 and a._thread.is_alive()                    # it retried
    a.close()
