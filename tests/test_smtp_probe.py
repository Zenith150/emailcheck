"""
Unit tests for the genuine SMTP Recipient Probing module (smtp_probe.py).
Tests mock all socket and SMTP client operations so tests run fast, isolated,
and without requiring outbound port 25 or real external mail servers.
"""

import unittest
from unittest.mock import MagicMock, patch
import socket
import smtplib
import os

from smtp_probe import (
    probe_smtp_recipient,
    get_smtp_probe_config,
    is_smtp_probe_enabled,
    sanitize_smtp_message,
    reset_circuit_breaker,
    is_circuit_breaker_active
)


class TestSmtpProbeModule(unittest.TestCase):
    """Test suite for safe SMTP handshake protocol exchanges."""

    def setUp(self):
        reset_circuit_breaker()
        # Ensure default disabled unless explicitly enabled in a test
        if "ENABLE_SMTP_PROBE" in os.environ:
            del os.environ["ENABLE_SMTP_PROBE"]

    def tearDown(self):
        reset_circuit_breaker()
        if "ENABLE_SMTP_PROBE" in os.environ:
            del os.environ["ENABLE_SMTP_PROBE"]

    def test_smtp_disabled_by_default(self):
        """When ENABLE_SMTP_PROBE is unset or false, probe returns disabled without connecting."""
        res = probe_smtp_recipient("test@example.com", "mail.example.com")
        self.assertEqual(res["smtp_status"], "disabled")
        self.assertFalse(res["smtp_attempted"])
        self.assertIsNone(res["smtp_response_code"])
        self.assertIn("disabled by configuration", res["smtp_explanation"])

    def test_config_defaults_and_validation(self):
        """Configuration parser handles defaults and bounds check safely."""
        with patch.dict(os.environ, {
            "ENABLE_SMTP_PROBE": "true",
            "SMTP_PROBE_PORT": "invalid_port",
            "SMTP_PROBE_TIMEOUT": "999",
            "SMTP_HELO_HOSTNAME": "",
            "SMTP_PROBE_SENDER": "not_an_email"
        }):
            cfg = get_smtp_probe_config()
            self.assertTrue(cfg["enabled"])
            self.assertEqual(cfg["port"], 25)  # Fallback to 25
            self.assertEqual(cfg["timeout"], 5.0)  # Bound to 5.0
            self.assertEqual(cfg["helo_hostname"], "mail.emailcheck.app")
            self.assertEqual(cfg["sender"], "verify@emailcheck.app")

    def test_null_mx_rejection_before_connecting(self):
        """RFC 7505 Null MX servers ('0 .' or '.') must be rejected before establishing connection."""
        with patch.dict(os.environ, {"ENABLE_SMTP_PROBE": "true"}):
            res_dot = probe_smtp_recipient("user@nullmx.org", ".")
            self.assertEqual(res_dot["smtp_status"], "rejected")
            self.assertFalse(res_dot["smtp_attempted"])
            self.assertIn("Null MX", res_dot["smtp_explanation"])

            res_empty = probe_smtp_recipient("user@nullmx.org", "")
            self.assertEqual(res_empty["smtp_status"], "unavailable")
            self.assertFalse(res_empty["smtp_attempted"])

    def test_successful_recipient_acceptance_250(self):
        """Mocked SMTP server accepting recipient with 250 OK."""
        mock_client = MagicMock()
        mock_client.connect.return_value = (220, "mail.example.com ESMTP Postfix")
        mock_client.ehlo.return_value = (250, "250-mail.example.com\n250 DSN")
        mock_client.mail.return_value = (250, "250 2.1.0 Sender Ok")

        # First rcpt for actual email returns 250; second rcpt for fake probe returns 550 (not catch-all)
        mock_client.rcpt.side_effect = [
            (250, "250 2.1.5 Recipient Ok"),
            (550, "550 5.1.1 No such user")
        ]

        mock_smtp_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, {"ENABLE_SMTP_PROBE": "true"}):
            res = probe_smtp_recipient(
                "user@example.com",
                "mail.example.com",
                smtp_client_class=mock_smtp_class
            )

        self.assertEqual(res["smtp_status"], "accepted")
        self.assertTrue(res["smtp_attempted"])
        self.assertEqual(res["smtp_response_code"], 250)
        self.assertIn("Recipient accepted", res["smtp_explanation"])
        self.assertEqual(res["smtp_server"], "mail.example.com")
        self.assertGreaterEqual(res["smtp_duration_ms"], 0.0)

        # Confirm protocol cleanliness
        mock_client.connect.assert_called_once_with("mail.example.com", 25)
        mock_client.ehlo.assert_called_once()
        mock_client.mail.assert_called_once()
        mock_client.rset.assert_called_once()
        mock_client.quit.assert_called_once()

        # CRITICAL: Verify DATA was NEVER called!
        self.assertFalse(mock_client.data.called, "DATA command must NEVER be issued!")

    def test_explicit_recipient_rejection_550(self):
        """Remote mail server explicitly rejecting unknown recipient (550)."""
        mock_client = MagicMock()
        mock_client.connect.return_value = (220, "smtp.example.com ESMTP")
        mock_client.ehlo.return_value = (250, "250-smtp.example.com")
        mock_client.mail.return_value = (250, "250 Ok")
        mock_client.rcpt.return_value = (550, "550 5.1.1 User unknown / Mailbox not found")

        mock_smtp_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, {"ENABLE_SMTP_PROBE": "true"}):
            res = probe_smtp_recipient(
                "nonexistent@example.com",
                "smtp.example.com",
                smtp_client_class=mock_smtp_class
            )

        self.assertEqual(res["smtp_status"], "rejected")
        self.assertTrue(res["smtp_attempted"])
        self.assertEqual(res["smtp_response_code"], 550)
        self.assertIn("explicitly rejected recipient", res["smtp_explanation"])
        self.assertFalse(mock_client.data.called)

    def test_temporary_rejection_450_greylisting(self):
        """Temporary SMTP failure (450 Greylisting) must be marked inconclusive, not rejected."""
        mock_client = MagicMock()
        mock_client.connect.return_value = (220, "smtp.example.com ESMTP")
        mock_client.ehlo.return_value = (250, "250-smtp.example.com")
        mock_client.mail.return_value = (250, "250 Ok")
        mock_client.rcpt.return_value = (450, "450 4.2.0 Greylisted, retry later")

        mock_smtp_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, {"ENABLE_SMTP_PROBE": "true"}):
            res = probe_smtp_recipient(
                "user@example.com",
                "smtp.example.com",
                smtp_client_class=mock_smtp_class
            )

        self.assertEqual(res["smtp_status"], "inconclusive")
        self.assertEqual(res["smtp_response_code"], 450)
        self.assertIn("Temporary SMTP response or greylisting", res["smtp_explanation"])

    def test_catch_all_domain_marked_inconclusive(self):
        """When server accepts both real and randomized invalid address, mark inconclusive."""
        mock_client = MagicMock()
        mock_client.connect.return_value = (220, "smtp.catchall.org ESMTP")
        mock_client.ehlo.return_value = (250, "250 Ok")
        mock_client.mail.return_value = (250, "250 Ok")
        # Both addresses accepted with 250
        mock_client.rcpt.side_effect = [
            (250, "250 Recipient accepted"),
            (250, "250 Catch-all accepted")
        ]

        mock_smtp_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, {"ENABLE_SMTP_PROBE": "true"}):
            res = probe_smtp_recipient(
                "random_user@catchall.org",
                "smtp.catchall.org",
                smtp_client_class=mock_smtp_class
            )

        self.assertEqual(res["smtp_status"], "inconclusive")
        self.assertIn("catch-all", res["smtp_explanation"])

    def test_connection_timeout_trips_circuit_breaker(self):
        """Socket timeout on port 25 marks probe unavailable and trips circuit breaker."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = socket.timeout("timed out")
        mock_smtp_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, {"ENABLE_SMTP_PROBE": "true"}):
            res = probe_smtp_recipient(
                "user@example.com",
                "mail.blocked-host.com",
                smtp_client_class=mock_smtp_class
            )

            self.assertEqual(res["smtp_status"], "unavailable")
            self.assertIn("timed out", res["smtp_explanation"])
            self.assertTrue(is_circuit_breaker_active(), "Port 25 timeout must trip circuit breaker")

            # Subsequent probe should be skipped immediately by circuit breaker
            res_subsequent = probe_smtp_recipient(
                "another@example.com",
                "mail.another-host.com",
                smtp_client_class=mock_smtp_class
            )
            self.assertEqual(res_subsequent["smtp_status"], "unavailable")
            self.assertFalse(res_subsequent["smtp_attempted"])
            self.assertIn("Circuit breaker active", res_subsequent["smtp_explanation"])

    def test_connection_refused_marks_unavailable(self):
        """ConnectionRefusedError on port 25 marks probe unavailable."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = ConnectionRefusedError("Connection refused")
        mock_smtp_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, {"ENABLE_SMTP_PROBE": "true"}):
            res = probe_smtp_recipient(
                "user@example.com",
                "mail.example.com",
                smtp_client_class=mock_smtp_class
            )

        self.assertEqual(res["smtp_status"], "unavailable")
        self.assertIn("blocked or unreachable", res["smtp_explanation"])

    def test_sanitize_smtp_message_utility(self):
        """Sanitizer strips CRLF, non-printables, and bounds string lengths."""
        dirty = "250-Ok \r\n\t Line 2\x00\x08<script>alert(1)</script>"
        clean = sanitize_smtp_message(dirty, max_len=100)
        self.assertNotIn("\r", clean)
        self.assertNotIn("\n", clean)
        self.assertNotIn("\x00", clean)
        self.assertIn("250-Ok", clean)

        # Truncation
        long_msg = "A" * 500
        truncated = sanitize_smtp_message(long_msg, max_len=50)
        self.assertEqual(len(truncated), 53)  # 50 + "..."
        self.assertTrue(truncated.endswith("..."))


if __name__ == "__main__":
    unittest.main()
