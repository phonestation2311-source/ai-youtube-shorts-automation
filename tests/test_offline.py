"""
Offline tests - no API keys, no internet, nothing is uploaded.
Run:  python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import ai_engine  # noqa: E402
from modules import script_quality  # noqa: E402
from modules import video_builder  # noqa: E402

GOOD_STORY = (
    "जंगल में आज एक अनोखी दावत होने वाली थी। "
    "खरगोश चीकू सबसे मीठी गाजर लाना चाहता था। "
    "पर गाजर का खेत नदी के उस पार था। "
    "चीकू को तैरना नहीं आता था, इसलिए वह किनारे पर उदास बैठ गया। "
    "तभी उसका दोस्त कछुआ मोती धीरे-धीरे आया। "
    "मोती बोला, चिंता मत करो, मेरी पीठ पर बैठ जाओ। "
    "मोती आराम से तैरता हुआ नदी पार ले गया। "
    "चीकू ने कहा, दोस्त साथ हों तो हर मुश्किल आसान है। "
    "सीख: सच्चे दोस्त हमेशा एक दूसरे की मदद करते हैं।"
)


class HelperTests(unittest.TestCase):
    def test_devanagari_ratio(self):
        self.assertGreater(ai_engine.devanagari_ratio(GOOD_STORY), 0.95)
        self.assertLess(ai_engine.devanagari_ratio("This is English only"), 0.1)

    def test_clean_story_removes_title_and_markdown(self):
        raw = "**चीकू की दावत**\n\n```\nशीर्षक: चीकू\n" + GOOD_STORY + "\n```\n(Word count: 98)"
        cleaned = ai_engine.clean_story_text(raw)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("शीर्षक", cleaned)
        self.assertNotIn("Word count", cleaned)
        self.assertTrue(cleaned.startswith("जंगल में"))

    def test_detect_animals(self):
        self.assertEqual(ai_engine.detect_animals(GOOD_STORY)[:2], ["rabbit", "turtle"])
        # "गाया" (sang) must not be detected as "गाय" (cow)
        self.assertEqual(ai_engine.detect_animals("उसने एक गाना गाया।"), [])

    def test_child_safety(self):
        self.assertTrue(ai_engine.is_child_safe(GOOD_STORY))
        self.assertFalse(ai_engine.is_child_safe("शेर ने बंदूक उठाई।"))

    def test_quality_check_approves_good_hindi_story(self):
        q = script_quality.validate_script(GOOD_STORY)
        self.assertTrue(q["required_ok"], q)
        self.assertTrue(q["approved"], q)

    def test_quality_check_rejects_english(self):
        q = script_quality.validate_script("Did you know corals can heal themselves? " * 10)
        self.assertFalse(q["required_ok"])


class MockedGroqTests(unittest.TestCase):
    """The Groq API is replaced by fake answers - no network, no key needed."""

    def test_story_pipeline_with_fake_groq(self):
        answers = iter([
            "खरगोश चीकू और कछुआ मोती नदी पार करके दावत के लिए गाजर लाते हैं",
            "**चीकू की दावत**\n" + GOOD_STORY,
            "क्या खरगोश चीकू आज नदी पार कर पाएगा?",
            json.dumps({"title": "🐰 चीकू और मोती की दोस्ती | Hindi Kids Story",
                        "description": "एक प्यारी कहानी।", "tags": ["हिंदी कहानी", "kids story"]},
                       ensure_ascii=False),
            "cute rabbit\nbaby turtle\nrabbit eating carrot\nscary shark\n1. turtle swimming",
        ])
        with mock.patch.object(ai_engine, "ask_ollama", side_effect=lambda *a, **k: next(answers)):
            idea = ai_engine.generate_viral_idea([], {"themes": ["दोस्ती"]})
            self.assertIn("चीकू", idea)
            story = ai_engine.generate_script(idea)
            self.assertTrue(story.startswith("जंगल में"))
            story = ai_engine.optimize_hook(story)
            self.assertTrue(story.startswith("क्या खरगोश चीकू"))
            seo = ai_engine.generate_seo(idea, story)
            self.assertTrue(seo["title"].endswith("#Shorts"))
            self.assertIn("चीकू", seo["title"])
            kws = ai_engine.generate_search_keywords(story, idea)
            self.assertEqual(len(kws), 5)
            self.assertNotIn("scary shark", kws)
            self.assertIn("cute rabbit", kws)

    def test_english_story_is_rejected(self):
        with mock.patch.object(ai_engine, "ask_ollama", return_value="Once upon a time a rabbit lived."):
            self.assertEqual(ai_engine.generate_script("idea"), "")

    def test_empty_groq_answer_is_retried(self):
        empty = mock.Mock(status_code=200)
        empty.json.return_value = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        good = mock.Mock(status_code=200)
        good.json.return_value = {"choices": [{"message": {"content": "नमस्ते"}, "finish_reason": "stop"}]}
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), \
                mock.patch.object(ai_engine.requests, "post", side_effect=[empty, good]) as post, \
                mock.patch.object(ai_engine.time, "sleep"):
            self.assertEqual(ai_engine.ask_ollama("hi"), "नमस्ते")
            self.assertEqual(post.call_count, 2)

    def test_missing_key_returns_empty(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            self.assertEqual(ai_engine.ask_ollama("hi"), "")


class SubtitleTests(unittest.TestCase):
    def test_ass_file_uses_devanagari_font_and_timings(self):
        words = GOOD_STORY.split()
        timings = [{"text": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate(words)]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.ass")
            video_builder.generate_ass_subtitles(GOOD_STORY, 40.0, path, timings)
            with open(path, encoding="utf-8") as f:
                text = f.read()
        self.assertIn("PlayResX: 1080", text)
        self.assertIn("PlayResY: 1920", text)
        self.assertIn("Noto Sans Devanagari", text)
        self.assertIn("चीकू", text)


class UploadSafetyTests(unittest.TestCase):
    def test_upload_is_off_by_default(self):
        from config import settings
        if os.getenv("UPLOAD_ENABLED", "").lower() in ("1", "true", "yes", "on"):
            self.skipTest("UPLOAD_ENABLED is set in your environment")
        self.assertFalse(settings.UPLOAD_ENABLED)
        from modules import youtube_upload
        with mock.patch.object(youtube_upload, "get_authenticated_service") as auth:
            self.assertIsNone(youtube_upload.upload_video("x.mp4", "t", "d"))
            auth.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
