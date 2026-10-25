"""
Unit tests for EmailCheck verification engine (verifier.py).
Mocks all external DNS and SMTP operations so test execution is fast,
isolated, and independent of external networks.
"""

import unittest
from unittest.mock import patch, MagicMock
import socket
import smtplib
import dns.resolver
import dns.exception

from verifier import (
    validate_syntax,
    check_domain_dns,
    check_smtp_recipient,
    classify_result,
    verify_single_email,
    verify_email_list
)


class TestEmailSyntaxValidation(unittest.TestCase):
    """Test RFC 5322 syntax validation logic."""

    def test_valid_emails(self):
        valid_cases = [
            "user@example.com",
            "first.last@company.org",
            "customer+tag@service.co.uk",
            "dev_team@sub.domain.io",
            "123456@numbers.net"
        ]
        for email in valid_cases:
            valid, local, domain, err = validate_syntax(email)
            self.assertTrue(valid, f"Expected {email} to be valid, got error: {err}")
            self.assertIsNone(err)
            self.assertTrue(len(local) > 0)
            self.assertTrue(len(domain) > 0)

    def test_invalid_syntax_formats(self):
        invalid_cases = [
            ("", "empty"),
            ("plainaddress", "Missing '@'"),
            ("@missinglocal.com", "Missing local part"),
            ("missingdomain@", "Missing domain part"),
            ("user@@doubleat.com", "multiple '@'"),
            ("user name@space.com", "syntax"),
            ("user..dots@example.com", "consecutive dots"),
            (".leadingdot@example.com", "start or end with a dot"),
            ("trailingdot.@example.com", "start or end with a dot"),
            ("user@domain..com", "consecutive dots"),
            ("user@nodot", "valid top-level domain"),
            ("a" * 65 + "@domain.com", "Local part exceeds 64 characters"),
            ("user@" + "a" * 250 + ".com", "exceeds")
        ]
        for email, expected_fragment in invalid_cases:
            valid, local, domain, err = validate_syntax(email)
            self.assertFalse(valid, f"Expected {email} to be invalid")
            self.assertIsNotNone(err)


class TestDomainDNSVerification(unittest.TestCase):
    """Test DNS and MX record resolution with mocked dnspython."""

    def setUp(self):
        self.mock_resolver = MagicMock()

    def test_domain_with_active_mx(self):
        mock_mx1 = MagicMock()
        mock_mx1.preference = 10
        mock_mx1.exchange = "mail.example.com."
        mock_mx2 = MagicMock()
        mock_mx2.preference = 20
        mock_mx2.exchange = "backup.example.com."

        self.mock_resolver.resolve.return_value = [mock_mx2, mock_mx1]

        result = check_domain_dns("example.com", resolver=self.mock_resolver)
        self.assertEqual(result["domain_status"], "exists")
        self.assertEqual(result["mx_status"], "mx_found")
        self.assertEqual(result["primary_mx"], "mail.example.com")
        self.assertEqual(len(result["mx_records"]), 2)

    def test_domain_nxdomain(self):
        self.mock_resolver.resolve.side_effect = dns.resolver.NXDOMAIN()

        result = check_domain_dns("nonexistent.invalid", resolver=self.mock_resolver)
        self.assertEqual(result["domain_status"], "nonexistent")
        self.assertEqual(result["mx_status"], "none")
        self.assertIn("NXDOMAIN", result["error"])

    def test_rfc5321_implicit_mx_fallback_a_record(self):
        # MX raises NoAnswer, but A record succeeds
        def resolve_side_effect(qname, rdtype):
            if rdtype == "MX":
                raise dns.resolver.NoAnswer()
            elif rdtype == "A":
                mock_a = MagicMock()
                mock_a.__str__.return_value = "93.184.216.34"
                return [mock_a]
            raise dns.resolver.NoAnswer()

        self.mock_resolver.resolve.side_effect = resolve_side_effect

        result = check_domain_dns("example.com", resolver=self.mock_resolver)
        self.assertEqual(result["domain_status"], "exists")
        self.assertEqual(result["mx_status"], "implicit_mx_found")
        self.assertEqual(result["primary_mx"], "example.com")
        self.assertIn("Implicit MX via A record", result["mx_records"][0])

    def test_domain_without_mx_and_without_a_record(self):
        # Both MX and A/AAAA raise NoAnswer
        self.mock_resolver.resolve.side_effect = dns.resolver.NoAnswer()

        result = check_domain_dns("no-mail.org", resolver=self.mock_resolver)
        self.assertEqual(result["domain_status"], "exists")
        self.assertEqual(result["mx_status"], "no_records")
        self.assertIn("no MX, A, or AAAA", result["error"])

    def test_dns_timeout(self):
        self.mock_resolver.resolve.side_effect = dns.resolver.LifetimeTimeout()

        result = check_domain_dns("timeout.org", resolver=self.mock_resolver)
        self.assertEqual(result["domain_status"], "dns_timeout")
        self.assertEqual(result["mx_status"], "dns_timeout")
        self.assertIn("timed out", result["error"])


class TestSMTPVerification(unittest.TestCase):
    """Test safe SMTP verification with mocked smtplib."""

    @patch("verifier.smtplib.SMTP")
    def test_smtp_mailbox_accepted(self, mock_smtp_class):
        mock_client = MagicMock()
        mock_smtp_class.return_value = mock_client

        mock_client.connect.return_value = (220, b"mx.example.com ESMTP ready")
        mock_client.mail.return_value = (250, b"Sender OK")
        # Primary recipient returns 250, probe recipient returns 550 (not catch-all)
        mock_client.rcpt.side_effect = [
            (250, b"Recipient OK"),
            (550, b"User unknown (catch-all probe)")
        ]

        result = check_smtp_recipient("valid.user@example.com", "mx.example.com")
        self.assertEqual(result["smtp_status"], "mailbox_accepted")
        self.assertFalse(result["is_catch_all"])
        self.assertEqual(result["code"], 250)

    @patch("verifier.smtplib.SMTP")
    def test_smtp_catch_all_detected(self, mock_smtp_class):
        mock_client = MagicMock()
        mock_smtp_class.return_value = mock_client

        mock_client.connect.return_value = (220, b"mx.example.com ESMTP ready")
        mock_client.mail.return_value = (250, b"Sender OK")
        # Both primary recipient AND nonexistent probe recipient return 250
        mock_client.rcpt.side_effect = [
            (250, b"Recipient OK"),
            (250, b"Recipient OK (catch-all accepted)")
        ]

        result = check_smtp_recipient("any.user@catchall.com", "mx.catchall.com")
        self.assertEqual(result["smtp_status"], "catch_all")
        self.assertTrue(result["is_catch_all"])

    @patch("verifier.smtplib.SMTP")
    def test_smtp_permanent_rejection(self, mock_smtp_class):
        mock_client = MagicMock()
        mock_smtp_class.return_value = mock_client

        mock_client.connect.return_value = (220, b"mx.example.com ESMTP ready")
        mock_client.mail.return_value = (250, b"Sender OK")
        mock_client.rcpt.return_value = (550, b"5.1.1 User unknown")

        result = check_smtp_recipient("baduser@example.com", "mx.example.com")
        self.assertEqual(result["smtp_status"], "mailbox_rejected")
        self.assertEqual(result["code"], 550)
        self.assertIn("rejected", result["reason"])

    @patch("verifier.smtplib.SMTP")
    def test_smtp_temporary_failure_greylisting(self, mock_smtp_class):
        mock_client = MagicMock()
        mock_smtp_class.return_value = mock_client

        mock_client.connect.return_value = (220, b"mx.example.com ESMTP ready")
        mock_client.mail.return_value = (250, b"Sender OK")
        mock_client.rcpt.return_value = (451, b"4.7.1 Greylisted, please try again later")

        result = check_smtp_recipient("greylisted@example.com", "mx.example.com")
        self.assertEqual(result["smtp_status"], "temporary_failure")
        self.assertEqual(result["code"], 451)

    @patch("verifier.smtplib.SMTP")
    def test_smtp_connection_blocked_or_refused(self, mock_smtp_class):
        mock_client = MagicMock()
        mock_smtp_class.return_value = mock_client
        mock_client.connect.side_effect = ConnectionRefusedError("Connection refused on port 25")

        result = check_smtp_recipient("user@blocked-host.com", "mx.blocked-host.com")
        self.assertEqual(result["smtp_status"], "connection_failed")
        self.assertIn("blocked", result["reason"].lower())

    @patch("verifier.smtplib.SMTP")
    def test_smtp_timeout(self, mock_smtp_class):
        mock_client = MagicMock()
        mock_smtp_class.return_value = mock_client
        mock_client.connect.side_effect = socket.timeout("Timed out")

        result = check_smtp_recipient("user@timeout-host.com", "mx.timeout-host.com")
        self.assertEqual(result["smtp_status"], "timeout")
        self.assertIn("timed out", result["reason"].lower())


class TestClassificationLogic(unittest.TestCase):
    """Test classification into Likely to be Delivered, Likely to Bounce, and Unknown."""

    def test_syntax_invalid_classification(self):
        cls, reason = classify_result(
            syntax_valid=False,
            domain_status="untested",
            mx_status="untested",
            smtp_info=None,
            syntax_error="Missing @"
        )
        self.assertEqual(cls, "Likely to Bounce")
        self.assertIn("Invalid email syntax", reason)

    def test_nxdomain_classification(self):
        cls, reason = classify_result(
            syntax_valid=True,
            domain_status="nonexistent",
            mx_status="none",
            smtp_info=None
        )
        self.assertEqual(cls, "Likely to Bounce")
        self.assertIn("NXDOMAIN", reason)

    def test_no_mx_classification(self):
        cls, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="no_records",
            smtp_info=None
        )
        self.assertEqual(cls, "Likely to Bounce")
        self.assertIn("no MX or A records", reason)

    def test_dns_timeout_classification(self):
        cls, reason = classify_result(
            syntax_valid=True,
            domain_status="dns_timeout",
            mx_status="dns_timeout",
            smtp_info=None,
            domain_error="DNS resolution timed out"
        )
        self.assertEqual(cls, "Unknown")
        self.assertIn("could not be completed", reason)

    def test_standard_mx_found_classification(self):
        cls, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="mx_found",
            smtp_info=None
        )
        self.assertEqual(cls, "Likely to be Delivered")
        self.assertIn("active MX mail routing verified", reason)

    def test_smtp_rejected_classification(self):
        smtp_info = {
            "smtp_attempted": True,
            "smtp_status": "mailbox_rejected",
            "reason": "Mailbox not found (550)"
        }
        cls, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="mx_found",
            smtp_info=smtp_info
        )
        self.assertEqual(cls, "Likely to Bounce")
        self.assertIn("explicitly rejected mailbox", reason)

    def test_smtp_catch_all_classification(self):
        smtp_info = {
            "smtp_attempted": True,
            "smtp_status": "catch_all",
            "is_catch_all": True,
            "reason": "Catch-all domain"
        }
        cls, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="mx_found",
            smtp_info=smtp_info
        )
        self.assertEqual(cls, "Unknown")
        self.assertIn("catch-all", reason.lower())


class TestBatchVerificationAndDeduplication(unittest.TestCase):
    """Test batch processing, limits, and memoization of duplicate emails."""

    @patch("verifier.check_domain_dns")
    def test_duplicate_emails_are_memoized(self, mock_dns):
        mock_dns.return_value = {
            "domain": "example.com",
            "domain_status": "exists",
            "mx_status": "mx_found",
            "mx_records": ["mail.example.com (priority 10)"],
            "primary_mx": "mail.example.com",
            "error": None
        }

        # 3 identical emails in input
        emails = ["test@example.com", "Test@Example.com", "test@example.com"]
        result = verify_email_list(emails, perform_smtp=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["results"]), 3)
        # Check that DNS check was only called ONCE thanks to memoization!
        self.assertEqual(mock_dns.call_count, 1)

    def test_empty_email_list_raises_error(self):
        with self.assertRaises(ValueError):
            verify_email_list([], perform_smtp=False)

    def test_exceeding_max_limit_raises_error(self):
        oversized = [f"user{i}@example.com" for i in range(105)]
        with self.assertRaises(ValueError):
            verify_email_list(oversized, max_emails=100)


if __name__ == "__main__":
    unittest.main()
