import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yt_member_transcripts as m


class CleanTests(unittest.TestCase):
    def test_json3_joins_new_words_and_splits_on_pause(self):
        raw = json.dumps(
            {
                "events": [
                    {"tStartMs": 0, "dDurationMs": 4000, "segs": [{"utf8": "[Music]"}]},
                    {
                        "tStartMs": 6000,
                        "dDurationMs": 3000,
                        "segs": [{"utf8": "大家好"}, {"utf8": "，我係"}],
                    },
                    {"tStartMs": 9000, "aAppend": 1, "segs": [{"utf8": "\n"}]},
                    {"tStartMs": 9100, "dDurationMs": 2500, "segs": [{"utf8": "老余。"}]},
                    {"tStartMs": 20000, "dDurationMs": 3000, "segs": [{"utf8": "今日想講會員片。"}]},
                ]
            },
            ensure_ascii=False,
        )
        self.assertEqual(
            m.clean_raw(raw, ".json3"),
            "大家好，我係老余。\n\n今日想講會員片。",
        )

    def test_json3_english_line_wrap_becomes_space(self):
        raw = json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 0,
                        "dDurationMs": 2000,
                        "segs": [{"utf8": "hello"}, {"utf8": " there"}],
                    },
                    {"tStartMs": 2000, "segs": [{"utf8": "\n"}]},
                    {"tStartMs": 2100, "dDurationMs": 2000, "segs": [{"utf8": "friend"}]},
                ]
            }
        )
        self.assertEqual(m.clean_raw(raw, ".json3"), "hello there friend")

    def test_rolling_vtt_chinese(self):
        raw = """WEBVTT
Kind: captions
Language: zh-Hant

00:00:00.000 --> 00:00:02.000
<c>大家好</c>我係

00:00:00.800 --> 00:00:02.800
家好我係老余

00:00:01.600 --> 00:00:03.600
我係老余今日

00:00:02.400 --> 00:00:04.400
老余今日想講
"""
        self.assertEqual(m.clean_raw(raw, ".vtt"), "大家好我係老余今日想講")
        self.assertNotIn("WEBVTT", m.clean_raw(raw, ".vtt"))
        self.assertNotIn("-->", m.clean_raw(raw, ".vtt"))

    def test_rolling_vtt_english(self):
        raw = """WEBVTT

00:00:00.000 --> 00:00:02.000
hello everyone my name

00:00:00.500 --> 00:00:02.500
everyone my name is

00:00:01.000 --> 00:00:03.000
my name is John and

00:00:01.500 --> 00:00:03.500
is John and today
"""
        self.assertEqual(m.clean_raw(raw, ".vtt"), "hello everyone my name is John and today")

    def test_manual_srt_does_not_glue_unrelated_sentences(self):
        raw = """1
00:00:00,000 --> 00:00:02,000
我喜歡的東西不多。

2
00:00:02,000 --> 00:00:04,000
的確是這樣。

3
00:00:08,000 --> 00:00:10,000
下一題。
"""
        text = m.clean_raw(raw, ".srt")
        self.assertEqual(text, "我喜歡的東西不多。\n的確是這樣。\n\n下一題。")
        self.assertNotIn("我喜歡的確", text)

    def test_html_entity_and_music_cue(self):
        raw = """WEBVTT

00:00:00.000 --> 00:00:01.000
[Music]

00:00:01.200 --> 00:00:03.000
大家&amp;老余
"""
        self.assertEqual(m.clean_raw(raw, ".vtt"), "大家&老余")

    def test_choose_subtitle_prefers_traditional_json3(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_id = "abcdefghijk"
            (root / f"{video_id}.en.vtt").write_text("x", encoding="utf-8")
            (root / f"{video_id}.zh-Hans.vtt").write_text("x", encoding="utf-8")
            (root / f"{video_id}.zh-Hant-en.json3").write_text("x", encoding="utf-8")
            (root / f"{video_id}.zh-Hant.json3").write_text("x", encoding="utf-8")
            (root / f"{video_id}.info.json").write_text("{}", encoding="utf-8")
            chosen = m.choose_subtitle(root, video_id, "zh-Hant")
            self.assertIsNotNone(chosen)
            assert chosen is not None
            self.assertEqual(chosen.name, f"{video_id}.zh-Hant.json3")

    def test_pick_one_subtitle_language(self):
        info = {
            "subtitles": {"zh-Hant": [{"ext": "vtt"}]},
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
                "zh-Hans": [{"ext": "json3"}],
                "aa": [{"ext": "vtt"}],
            },
        }
        self.assertEqual(m.pick_subtitle_lang(info, "zh-Hant", fallback=True), "zh-Hant")
        self.assertIsNone(m.pick_subtitle_lang(info, "ja", fallback=False))
        only_auto = {
            "subtitles": {},
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
                "zh-Hans": [{"ext": "json3"}],
                "de": [{"ext": "vtt"}],
            },
        }
        self.assertEqual(m.pick_subtitle_lang(only_auto, "zh-Hant", fallback=True), "zh-Hans")

    def test_members_playlist_url(self):
        channel_id = "UCX6OQ3DkcsbYNE6H8uQQuVA"
        self.assertEqual(
            m.members_playlist_url(channel_id, "all"),
            "https://www.youtube.com/playlist?list=UUMOX6OQ3DkcsbYNE6H8uQQuVA",
        )
        self.assertEqual(
            m.members_playlist_url(channel_id, "videos"),
            "https://www.youtube.com/playlist?list=UUMFX6OQ3DkcsbYNE6H8uQQuVA",
        )
        with self.assertRaises(ValueError):
            m.members_playlist_url("not-a-channel", "all")

    def test_date_duration_and_markdown(self):
        self.assertEqual(m.fmt_date("20240301"), "2024-03-01")
        self.assertEqual(m.fmt_duration(75), "1:15")
        self.assertEqual(m.fmt_duration(3661), "1:01:01")
        text = m.render_md(
            {
                "id": "abcdefghijk",
                "title": "測試標題",
                "date": "2024-03-01",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "channel": "測試頻道",
                "duration": 75,
                "language": "zh-Hant",
                "subtitle_kind": "auto",
                "transcript": "大家好",
            }
        )
        self.assertIn("# 測試標題", text)
        self.assertIn("大家好", text)
        self.assertNotIn("-->", text)


if __name__ == "__main__":
    unittest.main()
