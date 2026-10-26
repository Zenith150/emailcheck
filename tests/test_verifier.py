"""
Unit tests for EmailCheck verification engine (verifier.py) and providers.py.
Mocks all external DNS, SMTP, and HTTP operations so tests run fast,
isolated, and independent of external networks.
"""

import unittest
from unittest.mock import patch, MagicMock
import socket
import smtplib
import urllib.error
import dns.resolver
import dns.exception

from verifier import (
    validate_syntax,
    normalize_email,
    check_domain_dns,
    check_smtp_recipient,
    classify_result,
    verify_single_email,
    verify_email_list,
    check_domain_diagnostics,
    PIPELINE_STAGES
)
from providers import (
    is_disposable_domain,
    LocalFallbackProvider,
    AbstractAPIProvider,
    HunterProvider,
    ZeroBounceProvider,
    get_verification_provider
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


class TestEmailNormalization(unittest.TestCase):
    """Test email normalization without modifying local-part casing."""

    def test_normalization_rules(self):
        cases = [
            ("  John.Doe@EXAMPLE.COM.  ", "John.Doe", "example.com", "John.Doe@example.com"),
            ("User+Tag@Sub.Domain.Org", "User+Tag", "sub.domain.org", "User+Tag@sub.domain.org"),
            ("plain", "plain", "", "plain")
        ]
        for raw, expected_local, expected_dom, expected_full in cases:
            loc, dom, full = normalize_email(raw)
            self.assertEqual(loc, expected_local)
            self.assertEqual(dom, expected_dom)
            self.assertEqual(full, expected_full)


class TestDisposableDomainDetection(unittest.TestCase):
    """Test identification of temporary and disposable email domains."""

    def test_known_disposable_domains(self):
        disposable_list = [
            "mailinator.com",
            "sharklasers.com",
            "guerrillamail.com",
            "10minutemail.com",
            "tempmail.com",
            "yopmail.com",
            "burnermail.io"
        ]
        for d in disposable_list:
            self.assertTrue(is_disposable_domain(d), f"Expected {d} to be disposable")

    def test_legitimate_domains_are_not_disposable(self):
        legit_list = [
            "gmail.com",
            "google.com",
            "github.com",
            "microsoft.com",
            "yahoo.com",
            "company.co.uk"
        ]
        for d in legit_list:
            self.assertFalse(is_disposable_domain(d), f"Expected {d} NOT to be disposable")


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
        self.assertFalse(result["is_null_mx"])

    def test_rfc7505_null_mx_record(self):
        # RFC 7505 Null MX: preference 0, exchange '.'
        mock_null_mx = MagicMock()
        mock_null_mx.preference = 0
        mock_null_mx.exchange = "."

        self.mock_resolver.resolve.return_value = [mock_null_mx]

        result = check_domain_dns("nomail.example", resolver=self.mock_resolver)
        self.assertEqual(result["domain_status"], "exists")
        self.assertEqual(result["mx_status"], "null_mx")
        self.assertTrue(result["is_null_mx"])
        self.assertIn("Null MX", result["error"])

    def test_domain_nxdomain(self):
        self.mock_resolver.resolve.side_effect = dns.resolver.NXDOMAIN()

        result = check_domain_dns("nonexistent.invalid", resolver=self.mock_resolver)
        self.assertEqual(result["domain_status"], "nonexistent")
        self.assertEqual(result["mx_status"], "none")
        self.assertIn("NXDOMAIN", result["error"])

    def test_rfc5321_implicit_mx_fallback_a_record(self):
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


class TestProviderIntegration(unittest.TestCase):
    """Test HTTPS verification providers (Abstract, Hunter, ZeroBounce, Local)."""

    @patch("urllib.request.urlopen")
    def test_abstract_api_deliverable(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'''{
            "email": "alex@company.com",
            "deliverability": "DELIVERABLE",
            "quality_score": 0.95,
            "is_disposable_email": {"value": false},
            "is_catchall_email": {"value": false},
            "is_smtp_valid": {"value": true}
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        provider = AbstractAPIProvider(api_key="test_api_key")
        result = provider.verify_recipient("alex@company.com")

        self.assertEqual(result["status"], "deliverable")
        self.assertTrue(result["is_deliverable"])
        self.assertFalse(result["is_disposable"])
        self.assertEqual(result["provider"], "abstract")

    @patch("urllib.request.urlopen")
    def test_abstract_api_undeliverable(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'''{
            "email": "baduser@company.com",
            "deliverability": "UNDELIVERABLE",
            "quality_score": 0.10,
            "is_disposable_email": {"value": false},
            "is_catchall_email": {"value": false},
            "is_smtp_valid": {"value": false}
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        provider = AbstractAPIProvider(api_key="test_api_key")
        result = provider.verify_recipient("baduser@company.com")

        self.assertEqual(result["status"], "undeliverable")
        self.assertFalse(result["is_deliverable"])

    @patch("urllib.request.urlopen")
    def test_abstract_api_quota_exceeded(self, mock_urlopen):
        http_err = urllib.error.HTTPError(
            url="https://api.abstractapi.com",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=None
        )
        mock_urlopen.side_effect = http_err

        provider = AbstractAPIProvider(api_key="test_api_key")
        result = provider.verify_recipient("user@company.com")

        self.assertEqual(result["status"], "unknown")
        self.assertIn("quota", result["reason"].lower())

    @patch("urllib.request.urlopen")
    def test_hunter_api_deliverable(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'''{
            "data": {
                "result": "deliverable",
                "status": "valid",
                "score": 90,
                "disposable": false,
                "accept_all": false
            }
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        provider = HunterProvider(api_key="test_hunter_key")
        result = provider.verify_recipient("alex@huntertest.com")

        self.assertEqual(result["status"], "deliverable")
        self.assertTrue(result["is_deliverable"])
        self.assertEqual(result["provider"], "hunter")

    @patch("urllib.request.urlopen")
    def test_zerobounce_api_catch_all(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'''{
            "address": "sales@catchall.com",
            "status": "catch-all",
            "sub_status": ""
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        provider = ZeroBounceProvider(api_key="test_zb_key")
        result = provider.verify_recipient("sales@catchall.com")

        self.assertEqual(result["status"], "risky")
        self.assertTrue(result["is_catch_all"])

    def test_local_fallback_provider_without_key(self):
        provider = LocalFallbackProvider()
        res_regular = provider.verify_recipient("user@example.com")
        self.assertEqual(res_regular["status"], "unavailable")

        res_disposable = provider.verify_recipient("user@mailinator.com")
        self.assertEqual(res_disposable["status"], "risky")
        self.assertTrue(res_disposable["is_disposable"])


class TestClassificationLogic(unittest.TestCase):
    """Test 7-stage classification rules into Valid, Invalid, Risky, and Unknown."""

    def test_syntax_invalid_classification(self):
        cls, cat, reason = classify_result(
            syntax_valid=False,
            domain_status="untested",
            mx_status="untested",
            is_disposable=False,
            syntax_error="Missing @"
        )
        self.assertEqual(cls, "Invalid")
        self.assertEqual(cat, "invalid")
        self.assertIn("Invalid email syntax", reason)

    def test_nxdomain_classification(self):
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="nonexistent",
            mx_status="none",
            is_disposable=False
        )
        self.assertEqual(cls, "Invalid")
        self.assertEqual(cat, "invalid")
        self.assertIn("NXDOMAIN", reason)

    def test_rfc7505_null_mx_classification(self):
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="null_mx",
            is_disposable=False
        )
        self.assertEqual(cls, "Invalid")
        self.assertEqual(cat, "invalid")
        self.assertIn("Null MX", reason)

    def test_no_mx_classification(self):
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="no_records",
            is_disposable=False
        )
        self.assertEqual(cls, "Invalid")
        self.assertEqual(cat, "invalid")
        self.assertIn("no MX or A records", reason)

    def test_dns_timeout_classification(self):
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="dns_timeout",
            mx_status="dns_timeout",
            is_disposable=False,
            domain_error="DNS resolution timed out"
        )
        self.assertEqual(cls, "Unknown")
        self.assertEqual(cat, "unknown")
        self.assertIn("could not be completed", reason)

    def test_disposable_domain_classification(self):
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="mx_found",
            is_disposable=True
        )
        self.assertEqual(cls, "Risky")
        self.assertEqual(cat, "risky")
        self.assertIn("disposable", reason.lower())

    def test_provider_deliverable_classification(self):
        provider_res = {
            "status": "deliverable",
            "is_deliverable": True,
            "is_disposable": False,
            "reason": "Inbox exists"
        }
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="mx_found",
            is_disposable=False,
            provider_res=provider_res
        )
        self.assertEqual(cls, "Valid")
        self.assertEqual(cat, "valid")
        self.assertIn("confirmed deliverable", reason)

    def test_provider_undeliverable_classification(self):
        provider_res = {
            "status": "undeliverable",
            "is_deliverable": False,
            "is_disposable": False,
            "reason": "Mailbox does not exist"
        }
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="mx_found",
            is_disposable=False,
            provider_res=provider_res
        )
        self.assertEqual(cls, "Invalid")
        self.assertEqual(cat, "invalid")
        self.assertIn("undeliverable", reason)

    def test_provider_unavailable_unverified_recipient(self):
        provider_res = {
            "status": "unavailable",
            "is_deliverable": None,
            "is_disposable": False,
            "reason": "No provider configured"
        }
        cls, cat, reason = classify_result(
            syntax_valid=True,
            domain_status="exists",
            mx_status="mx_found",
            is_disposable=False,
            provider_res=provider_res
        )
        self.assertEqual(cls, "Risky")
        self.assertEqual(cat, "risky")
        self.assertIn("unverified", reason.lower())


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
            "is_null_mx": False,
            "error": None
        }

        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.verify_recipient.return_value = {
            "status": "deliverable",
            "is_deliverable": True,
            "is_disposable": False,
            "is_catch_all": False,
            "is_role": False,
            "score": 0.99,
            "provider": "mock",
            "raw_status": "ok",
            "reason": "Inbox active",
            "error": None
        }

        emails = ["test@example.com", "Test@Example.com", "test@example.com"]
        result = verify_email_list(emails, provider=mock_provider)

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(result["summary"]["valid"], 3)
        self.assertEqual(mock_dns.call_count, 1)

    def test_empty_email_list_raises_error(self):
        with self.assertRaises(ValueError):
            verify_email_list([])

    def test_exceeding_max_limit_raises_error(self):
        oversized = [f"user{i}@example.com" for i in range(105)]
        with self.assertRaises(ValueError):
            verify_email_list(oversized, max_emails=100)


class TestDomainDiagnosticsAndPipeline(unittest.TestCase):
    """Test suite for domain diagnostics tool, pipeline definitions, and v2.1 metadata."""

    def test_pipeline_stages_definition(self):
        """Authoritative pipeline definition must contain exactly 7 sequential stages."""
        self.assertEqual(len(PIPELINE_STAGES), 7)
        expected_names = [
            "Syntax Validation",
            "Email Normalization",
            "Disposable Domain Detection",
            "DNS Domain Validation",
            "MX and Null MX Validation",
            "Provider Recipient Verification",
            "Result Classification"
        ]
        for idx, stage in enumerate(PIPELINE_STAGES, 1):
            self.assertEqual(stage["id"], idx)
            self.assertEqual(stage["name"], expected_names[idx - 1])
            self.assertTrue(len(stage["description"]) > 10)

    @patch("verifier.check_domain_dns")
    def test_check_domain_diagnostics_active_mx(self, mock_dns):
        """Active MX domain should return can_receive_email=True and verdict Ready to Receive Mail."""
        mock_dns.return_value = {
            "domain": "google.com",
            "domain_status": "exists",
            "mx_status": "mx_found",
            "mx_records": ["smtp.google.com (priority 10)"],
            "primary_mx": "smtp.google.com",
            "is_null_mx": False,
            "error": None
        }

        result = check_domain_diagnostics("google.com")
        self.assertTrue(result["success"])
        self.assertTrue(result["syntax_valid"])
        self.assertTrue(result["can_receive_email"])
        self.assertFalse(result["is_null_mx"])
        self.assertFalse(result["is_disposable"])
        self.assertIn("Ready to Receive Mail", result["verdict"])
        self.assertIn("disclaimer", result)

    @patch("verifier.check_domain_dns")
    def test_check_domain_diagnostics_null_mx(self, mock_dns):
        """RFC 7505 Null MX domain should report can_receive_email=False and Rejects All Email."""
        mock_dns.return_value = {
            "domain": "nullmx.example.com",
            "domain_status": "exists",
            "mx_status": "null_mx",
            "mx_records": ["0 . (RFC 7505 Null MX)"],
            "primary_mx": None,
            "is_null_mx": True,
            "error": "Domain publishes RFC 7505 Null MX record."
        }

        result = check_domain_diagnostics("nullmx.example.com")
        self.assertTrue(result["success"])
        self.assertFalse(result["can_receive_email"])
        self.assertTrue(result["is_null_mx"])
        self.assertIn("Null MX", result["verdict"])

    @patch("verifier.check_domain_dns")
    def test_check_domain_diagnostics_nxdomain(self, mock_dns):
        """Nonexistent domain should report can_receive_email=False and Domain Nonexistent."""
        mock_dns.return_value = {
            "domain": "nonexistent-domain-12345.org",
            "domain_status": "nonexistent",
            "mx_status": "none",
            "mx_records": [],
            "primary_mx": None,
            "is_null_mx": False,
            "error": "NXDOMAIN"
        }

        result = check_domain_diagnostics("nonexistent-domain-12345.org")
        self.assertTrue(result["success"])
        self.assertFalse(result["can_receive_email"])
        self.assertIn("Nonexistent", result["verdict"])

    def test_check_domain_diagnostics_invalid_syntax(self):
        """Empty or invalid domain names should return success=False and an error message."""
        res_empty = check_domain_diagnostics("")
        self.assertFalse(res_empty["success"])
        self.assertIn("empty", res_empty["error"])

        res_invalid = check_domain_diagnostics("invalid_domain_without_tld")
        self.assertFalse(res_invalid["success"])
        self.assertIn("Invalid domain syntax", res_invalid["error"])

    def test_check_domain_diagnostics_disposable(self):
        """Disposable domain should be flagged as is_disposable=True."""
        result = check_domain_diagnostics("mailinator.com")
        self.assertTrue(result["is_disposable"])

    def test_verify_single_email_has_v2_1_diagnostics(self):
        """verify_single_email must return duration_ms, checked_at, and is_null_mx."""
        res = verify_single_email("bad..syntax@@domain")
        self.assertIn("duration_ms", res)
        self.assertIn("checked_at", res)
        self.assertIn("is_null_mx", res)
        self.assertFalse(res["syntax_valid"])
        self.assertIsInstance(res["duration_ms"], (int, float))


if __name__ == "__main__":
    unittest.main()
