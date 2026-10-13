import math

from barpi_monitor.levels import (SILENCE_FLOOR, MeterBallistics, OverDetector, SilenceDetector, channel_labels,
                                  format_db, parse_astats, parse_r128, to_db)


def test_parse_astats_orders_channels_and_handles_inf():
    meta = {
        "lavfi.astats.2.Peak_level": "-12.041200", "lavfi.astats.2.RMS_level": "-15.04",
        "lavfi.astats.1.Peak_level": "-6.020600", "lavfi.astats.1.RMS_level": "-inf",
        "lavfi.astats.Overall.Peak_level": "-6.0", "unrelated": "x",
    }
    peaks, rms = parse_astats(meta)
    assert peaks == [-6.0206, -12.0412]
    assert rms == [SILENCE_FLOOR, -15.04]


def test_parse_astats_empty():
    assert parse_astats(None) == ([], [])
    assert parse_astats({}) == ([], [])


def test_to_db_clamps_and_rejects_garbage():
    assert to_db("-inf") == SILENCE_FLOOR
    assert to_db("nan") == SILENCE_FLOOR
    assert to_db("abc") == SILENCE_FLOOR
    assert to_db(None) == SILENCE_FLOOR
    assert to_db("-3.5") == -3.5
    assert to_db("99") == 20.0


def test_parse_r128():
    assert parse_r128({"lavfi.r128.M": "-23.0", "lavfi.r128.S": "-22.5"}) == (-23.0, -22.5)
    assert parse_r128({}) == (SILENCE_FLOOR, SILENCE_FLOOR)


def test_ballistics_instant_attack_timed_release_and_hold():
    b = MeterBallistics(release_db_per_s=20, hold_seconds=1.0)
    b.update(0.0, [-20.0, -40.0], [-23.0, -43.0])
    assert [c.peak for c in b.channels] == [-20.0, -40.0]
    assert [c.hold for c in b.channels] == [-20.0, -40.0]
    b.update(0.5, [SILENCE_FLOOR, SILENCE_FLOOR], [SILENCE_FLOOR, SILENCE_FLOOR])
    assert math.isclose(b.channels[0].peak, -30.0)
    assert b.channels[0].hold == -20.0            # still holding
    b.update(0.6, [SILENCE_FLOOR, SILENCE_FLOOR], [SILENCE_FLOOR, SILENCE_FLOOR])
    assert math.isclose(b.channels[0].peak, -42.0)
    assert math.isclose(b.channels[0].hold, -32.0)  # hold expired, falls at 20 dB/s for 0.6 s
    b.update(0.1, [-5.0, -5.0], [-8.0, -8.0])
    assert b.channels[0].peak == -5.0 and b.channels[0].hold == -5.0


def test_ballistics_resizes_on_channel_change():
    b = MeterBallistics()
    b.update(0, [-10.0] * 2, [-13.0] * 2)
    b.update(0.04, [-10.0] * 6, [-13.0] * 6)
    assert len(b.channels) == 6
    b.decay(1.0)
    assert all(c.peak < -10.0 for c in b.channels)


def test_silence_detector():
    s = SilenceDetector(threshold_db=-50, hold_seconds=10)
    for _ in range(9):
        assert not s.update(1.0, [-70.0, -80.0])
    assert s.update(1.0, [-70.0, -80.0])
    assert not s.update(0.1, [-70.0, -30.0])       # one loud channel is enough
    assert s.silent_for == 0.0
    s.update(11, [])                                # no audio at all counts as silence
    assert s.active


def test_over_detector_latches_then_clears():
    o = OverDetector(over_db=-0.3, hold_seconds=2.0)
    assert not o.update(0.04, [-1.0, -2.0])
    assert o.update(0.04, [-0.1, -2.0])
    assert o.update(1.5, [-20.0, -20.0])
    assert not o.update(0.6, [-20.0, -20.0])
    assert o.count == 1


def test_channel_labels():
    assert channel_labels(2) == ["L", "R"]
    assert channel_labels(6, "5.1(side)") == ["L", "R", "C", "LFE", "Ls", "Rs"]
    assert channel_labels(3, "2.1") == ["L", "R", "LFE"]
    assert channel_labels(11) == [str(i) for i in range(1, 12)]


def test_format_db():
    assert format_db(SILENCE_FLOOR) == "-inf"
    assert format_db(-6.0206) == "-6.0"
    assert format_db(-6.4, 0) == "-6"


def test_sustained_condition():
    from barpi_monitor.levels import SustainedCondition
    s = SustainedCondition(hold_seconds=5)
    for _ in range(4):
        assert not s.update(1.0, True)
    assert s.update(1.0, True)
    assert not s.update(0.1, False)
    assert s.held_for == 0.0


def test_event_counter_window():
    from barpi_monitor.levels import EventCounter
    c = EventCounter(window_seconds=10)
    assert c.update(0.0, True) == 1
    assert c.update(4.0, True) == 2
    assert c.update(4.0, False) == 2
    assert c.update(3.0, True) == 2      # the first event (t=0) fell out of the 10 s window at t=11
    c.reset()
    assert c.count == 0


def test_missing_channels():
    from barpi_monitor.levels import missing_channels
    assert missing_channels([-20.0, -70.0], -50.0) == [1]
    assert missing_channels([-70.0, -20.0], -50.0) == [0]
    assert missing_channels([-70.0, -70.0], -50.0) == []      # both silent: that is SILENCE, not a missing channel
    assert missing_channels([-20.0, -20.0], -50.0) == []
    assert missing_channels([-20.0], -50.0) == []
    assert missing_channels([-20.0, -70.0, -70.0, -20.0], -50.0) == [1, 2]


def test_frame_signature():
    from barpi_monitor.levels import frame_signature
    black = bytes(1920 * 1080 * 4)
    sig_b, mean_b = frame_signature(black)
    assert mean_b == 0.0 and len(sig_b) > 1000
    grey = bytes([128, 128, 128, 0] * (1920 * 1080))
    sig_g, mean_g = frame_signature(grey)
    assert mean_g == 128.0 and sig_g != sig_b
    assert frame_signature(b"") == (b"", 0.0)
