"""
Offline tests for unattended runs - no API keys, no internet, nothing uploaded.
Run:  python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.settings as settings  # noqa: E402
from modules import run_guard  # noqa: E402
import run_job  # noqa: E402

STORY = "जंगल में खरगोश चीकू और कछुआ मोती रहते थे। दोनों ने मिलकर नदी पार की और दावत में गाजरें बाँटीं।"


class StateDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"STATE_DIR": self.tmp, "NOTIFY_WEBHOOK_URL": "", "NTFY_TOPIC": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class LockTests(StateDirTest):
    def test_second_run_is_blocked(self):
        with run_guard.RunLock():
            with self.assertRaises(run_guard.AlreadyRunning):
                with run_guard.RunLock():
                    pass
        with run_guard.RunLock():  # released after the first run
            pass

    def test_stale_lock_is_removed(self):
        lock = Path(self.tmp) / "run.lock"
        lock.write_text("old")
        old = time.time() - run_guard.LOCK_STALE_SECONDS - 10
        os.utime(lock, (old, old))
        with run_guard.RunLock():
            pass


class DuplicateTests(StateDirTest):
    def test_story_duplicate_detected(self):
        self.assertFalse(run_guard.is_duplicate_story(STORY))
        run_guard.record_story(STORY, "idea")
        self.assertTrue(run_guard.is_duplicate_story(STORY))
        self.assertFalse(run_guard.is_duplicate_story("हाथी गोलू और बंदर टिंकू ने मिलकर पेड़ पर झूला बनाया।"))

    def test_upload_ledger_blocks_same_file_and_title(self):
        video = Path(self.tmp) / "v.mp4"
        video.write_bytes(b"x" * 1000)
        self.assertEqual(run_guard.already_uploaded(str(video), "चीकू की दावत #Shorts"), "")
        run_guard.record_upload(str(video), "चीकू की दावत #Shorts", "abc123")
        self.assertIn("same video file", run_guard.already_uploaded(str(video), "Other"))
        other = Path(self.tmp) / "w.mp4"
        other.write_bytes(b"y" * 1000)
        self.assertIn("same title", run_guard.already_uploaded(str(other), "चीकू की दावत  #Shorts"))


class UploadGateTests(StateDirTest):
    def _result(self):
        video = Path(self.tmp) / "short_1.mp4"
        video.write_bytes(b"z" * 1000)
        meta = Path(self.tmp) / "short_1.json"
        meta.write_text(json.dumps({"title": "T #Shorts", "description": "d", "tags": ["a"]}), encoding="utf-8")
        return {"video_path": str(video), "metadata_path": str(meta)}

    def test_gate_closed_never_calls_youtube(self):
        with mock.patch.object(settings, "UPLOAD_ENABLED", False, create=True), \
                mock.patch.object(settings, "UPLOAD_APPROVED", False, create=True), \
                mock.patch("modules.youtube_upload.upload_video") as up:
            out = run_guard.safe_upload(self._result())
        self.assertFalse(out["uploaded"])
        up.assert_not_called()

    def test_only_one_gate_open_is_not_enough(self):
        with mock.patch.object(settings, "UPLOAD_ENABLED", True, create=True), \
                mock.patch.object(settings, "UPLOAD_APPROVED", False, create=True), \
                mock.patch("modules.youtube_upload.upload_video") as up:
            out = run_guard.safe_upload(self._result())
        self.assertFalse(out["uploaded"])
        up.assert_not_called()

    def test_duplicate_is_not_uploaded_twice(self):
        res = self._result()
        with mock.patch.object(settings, "UPLOAD_ENABLED", True, create=True), \
                mock.patch.object(settings, "UPLOAD_APPROVED", True, create=True), \
                mock.patch.object(run_guard, "channel_has_title", return_value=False), \
                mock.patch("modules.youtube_upload.upload_video", return_value="vid1") as up:
            first = run_guard.safe_upload(res)
            second = run_guard.safe_upload(res)
        self.assertTrue(first["uploaded"])
        self.assertFalse(second["uploaded"])
        self.assertIn("duplicate", second["reason"])
        self.assertEqual(up.call_count, 1)

    def test_uploader_itself_refuses_when_gate_closed(self):
        from modules import youtube_upload
        if getattr(settings, "UPLOAD_ENABLED", False) and getattr(settings, "UPLOAD_APPROVED", False):
            self.skipTest("gates are open in this environment")
        with mock.patch.object(youtube_upload, "get_authenticated_service") as auth:
            self.assertIsNone(youtube_upload.upload_video("x.mp4", "t", "d"))
            auth.assert_not_called()


class RunJobTests(StateDirTest):
    def test_failures_are_retried_limited_times_and_notified(self):
        fake = mock.Mock(return_value={"success": False, "error": "Groq down"})
        with mock.patch("main.create_single_video", fake), \
                mock.patch.object(run_guard, "notify") as note:
            code = run_job.run_once(max_attempts=2, retry_delay=0)
        self.assertEqual(code, 1)
        self.assertEqual(fake.call_count, 2)
        note.assert_called_once()
        last = json.loads((Path(self.tmp) / "last_run.json").read_text(encoding="utf-8"))
        self.assertEqual(last["status"], "failed")

    def test_success_does_not_upload_when_gate_closed(self):
        video = Path(self.tmp) / "short_9.mp4"
        video.write_bytes(b"v" * 1000)
        meta = Path(self.tmp) / "short_9.json"
        meta.write_text(json.dumps({"title": "T #Shorts", "story": STORY, "idea": "i"}, ensure_ascii=False), encoding="utf-8")
        fake = mock.Mock(return_value={"success": True, "video_path": str(video), "metadata_path": str(meta)})
        with mock.patch("main.create_single_video", fake), \
                mock.patch.object(settings, "UPLOAD_ENABLED", False, create=True), \
                mock.patch.object(settings, "UPLOAD_APPROVED", False, create=True), \
                mock.patch("modules.youtube_upload.upload_video") as up:
            code = run_job.run_once(max_attempts=2, retry_delay=0)
        self.assertEqual(code, 0)
        up.assert_not_called()
        self.assertTrue(fake.call_args.kwargs.get("dry_run"))
        last = json.loads((Path(self.tmp) / "last_run.json").read_text(encoding="utf-8"))
        self.assertEqual(last["status"], "ok")
        self.assertFalse(last["uploaded"])

    def test_locked_run_is_skipped(self):
        fake = mock.Mock()
        with run_guard.RunLock(), mock.patch("main.create_single_video", fake):
            self.assertEqual(run_job.run_once(max_attempts=1, retry_delay=0), 0)
        fake.assert_not_called()

    def test_notify_without_webhook_writes_failure_file(self):
        run_guard.notify("Test", "something broke")
        self.assertIn("something broke", (Path(self.tmp) / "last_failure.txt").read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class OutputCheckTests(unittest.TestCase):
    def test_checker_passes_good_and_flags_bad_video(self):
        from tools import check_outputs
        d = Path(tempfile.mkdtemp())
        try:
            for name, size, secs in (("short_good", "1080x1920", 25), ("short_bad", "640x360", 5)):
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={size}:r=30",
                                "-f", "lavfi", "-i", "sine=f=440", "-t", str(secs), "-shortest",
                                "-pix_fmt", "yuv420p", str(d / f"{name}.mp4")], check=True)
                (d / f"{name.replace('short_', 'thumb_')}.jpg").write_bytes(b"j")
                (d / f"{name}.json").write_text(json.dumps({
                    "title": "🐰 चीकू की दावत | Hindi Kids Story #Shorts", "description": "एक प्यारी कहानी बच्चों के लिए।",
                    "tags": ["a", "b", "c", "d", "e"], "story": STORY, "made_for_kids": True}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(check_outputs.check_video(d / "short_good.mp4"), [])
            self.assertTrue(check_outputs.check_video(d / "short_bad.mp4"))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
