"""
End-to-end publishing logic with a FAKE YouTube - nothing is uploaded.
Covers: publishing modes, login failure, wrong channel, duplicates (durable
content ID), upload errors + safe retry, exit codes, workflow mapping.
Run:  python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.settings as settings  # noqa: E402
from modules import run_guard  # noqa: E402
import run_job  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STORY = "जंगल में खरगोश चीकू और कछुआ मोती रहते थे। दोनों ने मिलकर नदी पार की।"
GOOD_CHANNEL = {"ok": True, "title": "ToonMasti Hindi TV 1M", "id": "UC1", "reason": ""}


class PipelineBase(unittest.TestCase):
    privacy = "private"
    public_ok = "false"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.video = self.tmp / "short_1.mp4"
        self.video.write_bytes(b"v" * 2048)
        self.meta = self.tmp / "short_1.json"
        self.meta.write_text(json.dumps({"title": "🐰 चीकू की दोस्ती | Hindi Kids Story #Shorts",
                                         "description": "कहानी", "tags": ["hindi kahani"], "story": STORY,
                                         "idea": "i"}, ensure_ascii=False), encoding="utf-8")
        self.result = {"success": True, "video_path": str(self.video), "metadata_path": str(self.meta)}
        self.yt = mock.MagicMock()
        self.patches = [
            mock.patch.dict(os.environ, {"STATE_DIR": str(self.tmp / "state"), "UPLOAD_PRIVACY": self.privacy,
                                         "UPLOAD_PUBLIC_APPROVED": self.public_ok,
                                         "NOTIFY_WEBHOOK_URL": "", "NTFY_TOPIC": ""}),
            mock.patch.object(settings, "UPLOAD_ENABLED", True, create=True),
            mock.patch.object(settings, "UPLOAD_APPROVED", True, create=True),
            mock.patch.object(run_guard, "validate_video", return_value=[]),
            mock.patch.object(run_guard, "UPLOAD_RETRY_WAIT", 0),
            mock.patch("modules.youtube_upload.get_authenticated_service", return_value=self.yt),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class PrivateModeTests(PipelineBase):
    def test_private_upload_goes_to_youtube_with_content_id(self):
        with mock.patch.object(run_guard, "verify_channel", return_value=GOOD_CHANNEL), \
                mock.patch.object(run_guard, "find_on_channel", return_value=""), \
                mock.patch("modules.youtube_upload.upload_video", return_value="VID1") as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual((out["status"], out["video_id"], out["privacy"]), ("uploaded", "VID1", "private"))
        kw = up.call_args.kwargs
        self.assertEqual(kw["privacy"], "private")
        self.assertIn(run_guard.content_id(STORY), kw["tags"])
        meta = json.loads(self.meta.read_text(encoding="utf-8"))
        self.assertEqual((meta["uploaded"], meta["video_id"], meta["privacy"]), (True, "VID1", "private"))

    def test_login_failure_is_reported_not_silent(self):
        with mock.patch("modules.youtube_upload.get_authenticated_service", return_value=None), \
                mock.patch("modules.youtube_upload.upload_video") as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual(out["status"], "auth_failed")
        up.assert_not_called()

    def test_wrong_channel_blocks_upload(self):
        bad = {"ok": False, "title": "Other", "id": "UC9", "reason": "logged in to 'Other'"}
        with mock.patch.object(run_guard, "verify_channel", return_value=bad), \
                mock.patch("modules.youtube_upload.upload_video") as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual(out["status"], "wrong_channel")
        up.assert_not_called()

    def test_same_story_never_uploaded_twice_even_as_new_file(self):
        with mock.patch.object(run_guard, "verify_channel", return_value=GOOD_CHANNEL), \
                mock.patch.object(run_guard, "find_on_channel", return_value=""), \
                mock.patch("modules.youtube_upload.upload_video", return_value="VID1") as up:
            run_guard.safe_upload(self.result)
            self.video.write_bytes(b"different render" * 200)  # re-rendered file, same story
            out = run_guard.safe_upload(self.result)
        self.assertEqual(out["status"], "duplicate")
        self.assertEqual(up.call_count, 1)

    def test_video_already_on_channel_is_not_uploaded_again(self):
        with mock.patch.object(run_guard, "verify_channel", return_value=GOOD_CHANNEL), \
                mock.patch.object(run_guard, "find_on_channel", return_value="OLD1"), \
                mock.patch("modules.youtube_upload.upload_video") as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual((out["status"], out["video_id"]), ("duplicate", "OLD1"))
        up.assert_not_called()

    def test_timeout_after_youtube_accepted_does_not_duplicate(self):
        # first check: not there; upload "fails"; second check: YouTube has it
        with mock.patch.object(run_guard, "verify_channel", return_value=GOOD_CHANNEL), \
                mock.patch.object(run_guard, "find_on_channel", side_effect=["", "LATE1"]), \
                mock.patch("modules.youtube_upload.upload_video", return_value=None) as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual((out["status"], out["video_id"]), ("uploaded", "LATE1"))
        self.assertEqual(up.call_count, 1)

    def test_upload_errors_retry_limited_then_fail(self):
        with mock.patch.object(run_guard, "verify_channel", return_value=GOOD_CHANNEL), \
                mock.patch.object(run_guard, "find_on_channel", return_value=""), \
                mock.patch("modules.youtube_upload.upload_video", return_value=None) as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual(out["status"], "upload_failed")
        self.assertEqual(up.call_count, run_guard.UPLOAD_ATTEMPTS)

    def test_invalid_video_is_not_uploaded(self):
        with mock.patch.object(run_guard, "validate_video", return_value=["no audio"]), \
                mock.patch("modules.youtube_upload.upload_video") as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual(out["status"], "video_invalid")
        up.assert_not_called()


class PublicModeTests(PipelineBase):
    privacy = "public"
    public_ok = "true"

    def test_public_upload_when_explicitly_approved(self):
        with mock.patch.object(run_guard, "verify_channel", return_value=GOOD_CHANNEL), \
                mock.patch.object(run_guard, "find_on_channel", return_value=""), \
                mock.patch("modules.youtube_upload.upload_video", return_value="PUB1") as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual((out["status"], out["privacy"]), ("uploaded", "public"))
        self.assertEqual(up.call_args.kwargs["privacy"], "public")


class PublicNotApprovedTests(PipelineBase):
    privacy = "public"
    public_ok = "false"

    def test_public_without_approval_is_config_error(self):
        with mock.patch("modules.youtube_upload.upload_video") as up:
            out = run_guard.safe_upload(self.result)
        self.assertEqual(out["status"], "config_error")
        up.assert_not_called()


class ExitCodeTests(PipelineBase):
    def _run(self, upload_status):
        fake_upload = {"status": upload_status, "uploaded": upload_status == "uploaded", "video_id": "V",
                       "privacy": "private", "reason": "r"}
        with mock.patch("main.create_single_video", return_value=self.result), \
                mock.patch.object(run_guard, "safe_upload", return_value=fake_upload), \
                mock.patch.object(run_guard, "is_duplicate_story", return_value=False), \
                mock.patch.object(run_guard, "notify") as note:
            code = run_job.run_once(max_attempts=1, retry_delay=0)
        return code, note

    def test_uploaded_is_success_and_notified(self):
        code, note = self._run("uploaded")
        self.assertEqual(code, 0)
        self.assertEqual(note.call_args.kwargs.get("level"), "info")

    def test_upload_problems_fail_the_run(self):
        for status in ("auth_failed", "upload_failed", "wrong_channel", "config_error", "video_invalid"):
            code, note = self._run(status)
            self.assertEqual(code, 1, status)
            self.assertIn(status, note.call_args.args[0])

    def test_disabled_is_not_a_failure(self):
        self.assertEqual(self._run("upload_disabled")[0], 0)


class HelperTests(unittest.TestCase):
    def test_content_id_is_stable_and_whitespace_insensitive(self):
        self.assertEqual(run_guard.content_id(STORY), run_guard.content_id("  " + STORY.replace(" ", "  ")))
        self.assertNotEqual(run_guard.content_id(STORY), run_guard.content_id(STORY + "!"))

    def test_verify_channel(self):
        yt = mock.MagicMock()
        yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "UC1", "snippet": {"title": "ToonMasti Hindi TV 1M"}}]}
        with mock.patch.dict(os.environ, {"EXPECTED_CHANNEL_ID": "", "EXPECTED_CHANNEL_TITLE": ""}):
            self.assertTrue(run_guard.verify_channel(yt)["ok"])
        with mock.patch.dict(os.environ, {"EXPECTED_CHANNEL_ID": "UC_OTHER"}):
            self.assertFalse(run_guard.verify_channel(yt)["ok"])

    def test_find_on_channel_matches_content_id_tag(self):
        yt = mock.MagicMock()
        yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}
        yt.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"videoId": "A1"}}]}
        yt.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "A1", "snippet": {"title": "x", "tags": ["ksidabc"]}}]}
        self.assertEqual(run_guard.find_on_channel(yt, "other title", "ksidabc"), "A1")
        self.assertEqual(run_guard.find_on_channel(yt, "other title", "ksidzzz"), "")

    def test_missing_optional_pexels_key_is_harmless(self):
        from modules import footage_fetcher
        with mock.patch.object(footage_fetcher, "PEXELS_API_KEY", ""), \
                mock.patch.object(footage_fetcher.requests, "get") as get:
            self.assertEqual(footage_fetcher.search_pexels_videos("cute rabbit"), [])
            get.assert_not_called()

    def test_token_problem_is_an_error_when_uploads_are_on(self):
        from tools import prepare_token
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"YOUTUBE_TOKEN_B64": "", "GITHUB_ACTIONS": "true", "GITHUB_OUTPUT": "",
                                          "UPLOAD_ENABLED": "true", "UPLOAD_APPROVED": "true"}), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(prepare_token.main(), 0)  # generation must still continue
        self.assertIn("::error", buf.getvalue())


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        import yaml
        self.wf = yaml.safe_load((ROOT / ".github/workflows/kids-shorts.yml").read_text(encoding="utf-8"))
        self.job = self.wf["jobs"]["make-short"]

    def test_publishing_variables_are_mapped_not_hardcoded(self):
        env = self.job["env"]
        self.assertEqual(env["UPLOAD_ENABLED"], "${{ vars.UPLOAD_ENABLED || 'false' }}")
        self.assertEqual(env["UPLOAD_APPROVED"], "${{ vars.UPLOAD_APPROVED || 'false' }}")
        self.assertEqual(env["UPLOAD_PRIVACY"], "${{ vars.UPLOAD_PRIVACY || 'private' }}")
        self.assertEqual(env["UPLOAD_PUBLIC_APPROVED"], "${{ vars.UPLOAD_PUBLIC_APPROVED || 'false' }}")

    def test_schedule_and_no_overlap(self):
        on = self.wf.get("on", self.wf.get(True))
        self.assertEqual(on["schedule"][0]["cron"], "30 4 * * *")  # 04:30 UTC = 06:30 SAST
        self.assertEqual(self.wf["concurrency"]["cancel-in-progress"], False)

    def test_daily_run_calls_real_upload_path_and_keeps_artifacts(self):
        steps = self.job["steps"]
        runs = [s.get("run", "") for s in steps]
        self.assertTrue(any("run_job.py --once" in r for r in runs))
        self.assertTrue(any("tools.prepare_token" in r for r in runs))
        self.assertTrue(any("rm -f state/*.lock" in r for r in runs))
        art = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))][0]
        self.assertEqual(art.get("if"), "always()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
