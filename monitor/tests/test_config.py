import json

from barpi_monitor.config import Config, Settings, Source, guess_name, is_url


def test_is_url_and_guess_name():
    assert is_url("rtsp://10.0.0.1/live")
    assert is_url("srt://10.0.0.5:9000?mode=caller")
    assert not is_url(r"C:\Video\promo.mp4")
    assert not is_url("/home/x/clip.mkv")
    assert guess_name(r"C:\Video\promo.mp4") == "promo"
    assert guess_name("https://cdn.example.com/live/index.m3u8") == "cdn.example.com"
    assert guess_name("https://cdn.example.com/channels/alpha.m3u8") == "cdn.example.com / alpha"
    assert guess_name("udp://@239.1.1.1:1234") == "239.1.1.1"


def test_source_flags():
    assert Source("a", "rtsp://x/y").is_stream
    assert not Source("a", "clip.mp4").is_stream
    assert Source("", "D:/clips/news.mxf").display_name() == "news"


def test_config_round_trip(tmp_path):
    path = tmp_path / "cfg" / "config.json"
    cfg = Config(sources=[Source("Cam 1", "rtsp://cam/1"), Source("Promo", "D:/promo.mp4", loop=True, silence_alarm=False)],
                 settings=Settings(silence_threshold_db=-45, volume=80), audible=1, mute_all=True, layout_columns=2)
    cfg.save(path)
    loaded = Config.load(path)
    assert loaded == cfg
    assert not (tmp_path / "cfg" / "config.tmp").exists()


def test_config_tolerates_unknown_and_missing_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"sources": [{"name": "x", "url": "rtsp://a", "future_field": 1}, {"name": "no url"}],
                                "settings": {"silence_seconds": 3, "bogus": True}, "extra": 5}))
    cfg = Config.load(path)
    assert [s.url for s in cfg.sources] == ["rtsp://a"]
    assert cfg.settings.silence_seconds == 3
    assert cfg.settings.volume == 100


def test_config_bad_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    cfg = Config.load(path)
    assert cfg == Config()
    assert (tmp_path / "config.bad.json").exists()


def test_missing_config_is_defaults(tmp_path):
    assert Config.load(tmp_path / "nope.json") == Config()


def test_new_settings_defaults_and_round_trip(tmp_path):
    cfg = Config(sources=[Source("a", "rtsp://x", level_alarm=False, video_alarm=False)],
                 settings=Settings(loud_lufs=-20, freeze_seconds=4, video_analysis=False), show_alarm_log=False)
    path = tmp_path / "c.json"
    cfg.save(path)
    loaded = Config.load(path)
    assert loaded == cfg
    assert not loaded.sources[0].level_alarm and not loaded.sources[0].video_alarm
    assert Settings().over_alarm and Settings().high_peak_events == 3 and Settings().black_level == 20.0
