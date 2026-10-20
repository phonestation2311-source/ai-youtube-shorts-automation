"""
Offline tests for safe publishing - no keys, no internet, NOTHING is uploaded
(the YouTube API is replaced by fakes).
Run:  python -m unittest discover -s tests -v
"""

import base64
import contextlib
import io
import json
import os
import pickle
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import run_guard  # noqa: E402
from tools import prepare_token  # noqa: E402

FAKE_TOKEN = pickle.dumps(types.SimpleNamespace(refresh_token="fake-refresh", token="fake-access"))


class TokenDecodeTests(unittest.TestCase):
    def test_clean_value(self):
        data, why = prepare_token.decode_token(base64.b64encode(FAKE_TOKEN).decode())
        self.assertEqual((data, why), (FAKE_TOKEN, ""))

    def test_copy_paste_damage_is_repaired(self):
        b64 = base64.b64encode(FAKE_TOKEN).decode()
        wrapped = "\r\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))
        for messy in (f'  "{wrapped}"  \n', b64.rstrip("="), base64.urlsafe_b64encode(FAKE_TOKEN).decode(),
                      base64.b64encode(b64.encode()).decode()):  # last one: encoded twice
            data, why = prepare_token.decode_token(messy)
            self.assertEqual(why, "")
            self.assertEqual(data, FAKE_TOKEN)

    def test_bad_values_give_reason_not_crash(self):
        for bad in ("", "   ", "not base64 at all!", "%%%%"):
            data, why = prepare_token.decode_token(bad)
            self.assertIsNone(data)
            self.assertTrue(why)

    def test_validate_token(self):
        self.assertEqual(prepare_token.validate_token(FAKE_TOKEN), "")
        self.assertTrue(prepare_token.validate_token(b"hello"))
        self.assertTrue(prepare_token.validate_token(pickle.dumps({"a": 1})))
        self.assertTrue(prepare_token.validate_token(pickle.dumps(types.SimpleNamespace(refresh_token=None))))


class PrepareTokenMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "gh_output"
        self.tok = self.tmp / "youtube_token.pickle"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, secret):
        buf = io.StringIO()
        env = {"YOUTUBE_TOKEN_B64": secret, "GITHUB_OUTPUT": str(self.out), "GITHUB_ACTIONS": "true"}
        with mock.patch.dict(os.environ, env), mock.patch("config.settings.YOUTUBE_TOKEN_FILE", str(self.tok)), \
                contextlib.redirect_stdout(buf):
            code = prepare_token.main()
        return code, buf.getvalue()

    def test_valid_secret_saved_and_never_printed(self):
        secret = base64.b64encode(FAKE_TOKEN).decode()
        code, printed = self._run(secret)
        self.assertEqual(code, 0)
        self.assertEqual(self.tok.read_bytes(), FAKE_TOKEN)
        self.assertNotIn(secret[:20], printed)
        self.assertIn("token_ok=true", self.out.read_text())

    def test_invalid_secret_never_fails_the_run(self):
        code, printed = self._run("this-is-broken!!")
        self.assertEqual(code, 0)
        self.assertFalse(self.tok.exists())
        self.assertIn("token_ok=false", self.out.read_text())
        self.assertNotIn("this-is-broken", printed)

    def test_missing_secret_never_fails_the_run(self):
        code, _ = self._run("")
        self.assertEqual(code, 0)
        self.assertIn("token_ok=false", self.out.read_text())


class PrivacyTests(unittest.TestCase):
    def test_default_is_private(self):
        with mock.patch.dict(os.environ, {"UPLOAD_PRIVACY": "", "UPLOAD_PUBLIC_APPROVED": ""}):
            self.assertEqual(run_guard.upload_privacy(), "private")

    def test_public_needs_third_approval(self):
        with mock.patch.dict(os.environ, {"UPLOAD_PRIVACY": "public", "UPLOAD_PUBLIC_APPROVED": "false"}):
            self.assertEqual(run_guard.upload_privacy(), "private")
        with mock.patch.dict(os.environ, {"UPLOAD_PRIVACY": "public", "UPLOAD_PUBLIC_APPROVED": "true"}):
            self.assertEqual(run_guard.upload_privacy(), "public")

    def test_unknown_value_is_private(self):
        with mock.patch.dict(os.environ, {"UPLOAD_PRIVACY": "everyone"}):
            self.assertEqual(run_guard.upload_privacy(), "private")


class UploaderBehaviourTests(unittest.TestCase):
    """Calls the real upload_video() with a FAKE YouTube client."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"STATE_DIR": str(self.tmp / "state"),
                                                "UPLOAD_PUBLIC_APPROVED": "false"})
        self.env.start()
        self.video = self.tmp / "short_x.mp4"
        self.video.write_bytes(b"\x00" * 4096)
        from modules import youtube_upload
        self.yu = youtube_upload
        if not hasattr(youtube_upload, "UPLOAD_APPROVED"):
            self.skipTest("uploader has no UPLOAD_APPROVED gate in this copy")
        self.gates = [mock.patch.object(youtube_upload, "UPLOAD_ENABLED", True),
                      mock.patch.object(youtube_upload, "UPLOAD_APPROVED", True)]
        for g in self.gates:
            g.start()

    def tearDown(self):
        for g in getattr(self, "gates", []):
            g.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_youtube(self):
        yt = mock.MagicMock()
        yt.videos.return_value.insert.return_value.next_chunk.return_value = (None, {"id": "FAKE123"})
        return yt

    def test_public_request_is_forced_private_and_made_for_kids(self):
        yt = self._fake_youtube()
        with mock.patch.object(self.yu, "get_authenticated_service", return_value=yt):
            vid = self.yu.upload_video(str(self.video), "चीकू #Shorts", "d", tags=["a"], privacy="public")
        self.assertEqual(vid, "FAKE123")
        body = yt.videos.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertIs(body["status"]["selfDeclaredMadeForKids"], True)

    def test_second_upload_of_same_video_is_blocked(self):
        yt = self._fake_youtube()
        with mock.patch.object(self.yu, "get_authenticated_service", return_value=yt) as auth:
            first = self.yu.upload_video(str(self.video), "चीकू #Shorts", "d")
            second = self.yu.upload_video(str(self.video), "चीकू #Shorts", "d")
        self.assertEqual(first, "FAKE123")
        self.assertIsNone(second)
        self.assertEqual(auth.call_count, 1)
        ledger = json.loads((self.tmp / "state" / "upload_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(len(ledger), 1)


class PublishCheckTests(unittest.TestCase):
    def test_dry_run_never_uploads(self):
        import run_job
        tmp = Path(tempfile.mkdtemp())
        try:
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {"STATE_DIR": str(tmp)}), \
                    mock.patch("config.settings.YOUTUBE_TOKEN_FILE", str(tmp / "missing.pickle")), \
                    mock.patch("modules.youtube_upload.upload_video") as up, \
                    contextlib.redirect_stdout(buf):
                code = run_job.publish_check()
            self.assertEqual(code, 1)
            self.assertIn("NOT PUBLISH-READY", buf.getvalue())
            up.assert_not_called()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
