import json
from importlib import import_module
from unittest.mock import patch
from urllib.error import URLError

from django.test import SimpleTestCase, TestCase, override_settings

from fg.apps import MumbleFgConfig
from fg.control import BgSyncError, _post_json, clear_handshake_throttle


class _JsonResponseStub:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ControlClientDiagnosticsTest(TestCase):
    def tearDown(self):
        clear_handshake_throttle()
        return super().tearDown()

    @override_settings(BG_PSK="")
    @patch("fg.control.control_keyring.decrypt_active_keypairs", return_value=[])
    @patch("fg.control.urlopen")
    def test_post_json_logs_when_no_auth_secret_is_available(self, mock_urlopen, _mock_keypairs):
        mock_urlopen.return_value = _JsonResponseStub({"status": "completed"})

        with self.assertLogs("fg.control", level="WARNING") as captured:
            _post_json("/v1/test", {"pkid": 1}, requested_by="tester")

        request = mock_urlopen.call_args.args[0]
        self.assertIsNone(request.get_header("X-fgbg-psk"))
        self.assertTrue(any("no authentication secret" in line for line in captured.output))
        self.assertTrue(any("auth_mode=none" in line for line in captured.output))

    @override_settings(BG_PSK="", MURMUR_CONTROL_HANDSHAKE_THROTTLE_SECONDS=60)
    @patch("fg.control.control_keyring.decrypt_active_keypairs", return_value=[])
    @patch("fg.control.urlopen")
    def test_post_json_logs_auth_context_when_throttling(self, mock_urlopen, _mock_keypairs):
        mock_urlopen.side_effect = URLError("connection refused")

        with self.assertLogs("fg.control", level="WARNING") as captured:
            with self.assertRaises(BgSyncError):
                _post_json("/v1/test", {"pkid": 1}, requested_by="tester")

        self.assertTrue(any("throttling control requests" in line for line in captured.output))
        self.assertTrue(any("auth_mode=none" in line for line in captured.output))


class FgPkiStartupDiagnosticsTest(SimpleTestCase):
    @patch("fg.crypto.fetch_from_bg")
    @patch("fg.crypto.initialize")
    @patch("fg.crypto.is_available", return_value=True)
    @patch(
        "fg.pki.startup_status",
        return_value={
            "private_key_path_present": True,
            "private_key_exists": True,
            "public_key_path_present": True,
            "public_key_exists": True,
            "passphrase_present": False,
            "can_decrypt": False,
        },
    )
    @patch("fg.pki.initialize", side_effect=RuntimeError("encrypted private key requires passphrase"))
    @patch("fg.pki.is_initialized", return_value=False)
    def test_ready_logs_pki_startup_failure(
        self,
        _mock_pki_initialized,
        _mock_pki_init,
        _mock_pki_status,
        _mock_crypto_available,
        _mock_crypto_init,
        _mock_crypto_fetch,
    ):
        config = MumbleFgConfig("fg", import_module("fg"))

        with self.assertLogs("fg.pki", level="WARNING") as captured:
            config.ready()

        self.assertTrue(any("FG PKI startup failed" in line for line in captured.output))
        self.assertTrue(any("passphrase_present=False" in line for line in captured.output))
