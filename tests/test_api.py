"""
Integration tests for EmailCheck Flask endpoints (app.py).
Tests REST API validation, responses, error handlers, and rate limiting.
"""

import unittest
from unittest.mock import patch, MagicMock
import json

from app import app, rate_limit_tracker


class TestEmailCheckAPI(unittest.TestCase):
    """Test suite for EmailCheck web endpoints."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        rate_limit_tracker.clear()

    def test_get_index_page(self):
        """Root GET request should render dashboard HTML."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"EmailCheck", response.data)
        self.assertIn(b"Verify Emails", response.data)

    def test_get_health_endpoint(self):
        """Health check endpoint should return healthy status, v2.1, and 7 pipeline stages."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "EmailCheck")
        self.assertEqual(data["version"], "2.1.0")
        self.assertIn("provider", data)
        self.assertIn("provider_configured", data)
        self.assertIn("smtp_outbound_available", data)
        self.assertEqual(data["pipeline_stage_count"], 7)
        self.assertEqual(len(data["pipeline_stages"]), 7)

    def test_get_pipeline_endpoint(self):
        """GET /api/pipeline returns authoritative pipeline stages."""
        response = self.client.get("/api/pipeline")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 7)
        self.assertEqual(len(data["stages"]), 7)

    @patch("app.check_domain_diagnostics")
    def test_api_domain_get_endpoint(self, mock_domain_diag):
        """GET /api/domain?domain=google.com should invoke diagnostics and return 200."""
        mock_domain_diag.return_value = {
            "success": True,
            "domain": "google.com",
            "syntax_valid": True,
            "domain_status": "exists",
            "mx_status": "mx_found",
            "mx_records": ["smtp.google.com"],
            "can_receive_email": True,
            "verdict": "Ready to Receive Mail",
            "confidence": "High"
        }
        response = self.client.get("/api/domain?domain=google.com")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["can_receive_email"])

    @patch("app.check_domain_diagnostics")
    def test_api_domain_post_endpoint(self, mock_domain_diag):
        """POST /api/domain with json payload should return diagnostics."""
        mock_domain_diag.return_value = {
            "success": True,
            "domain": "mailinator.com",
            "syntax_valid": True,
            "domain_status": "exists",
            "mx_status": "mx_found",
            "mx_records": ["mail2.mailinator.com"],
            "can_receive_email": True,
            "is_disposable": True,
            "verdict": "Ready to Receive Mail",
            "confidence": "High"
        }
        response = self.client.post(
            "/api/domain",
            data=json.dumps({"domain": "mailinator.com"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["is_disposable"])

    def test_api_domain_missing_parameter(self):
        """GET /api/domain without domain parameter should return 400 Bad Request."""
        response = self.client.get("/api/domain")
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("required", data["error"])

    def test_no_latex_arrows_in_templates(self):
        """Regression test: verify no LaTeX dollar arrow syntax in index.html template."""
        with open("templates/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn(r"$\rightarrow$", content)
        self.assertNotIn(r"\rightarrow", content)
        self.assertIn("Non-Invasive Verification Pipeline", content)
        self.assertIn("Email syntax", content)

    @patch("verifier.get_verification_provider")
    @patch("verifier.check_domain_dns")
    def test_api_verify_valid_batch(self, mock_dns, mock_get_provider):
        """POST /api/verify with valid input list returns structured results."""
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
        mock_provider.name = "abstract"
        mock_provider.verify_recipient.return_value = {
            "status": "deliverable",
            "is_deliverable": True,
            "is_disposable": False,
            "is_catch_all": False,
            "is_role": False,
            "score": 0.95,
            "provider": "abstract",
            "raw_status": "DELIVERABLE",
            "reason": "Recipient inbox verified deliverable.",
            "error": None
        }
        mock_get_provider.return_value = mock_provider

        payload = {
            "emails": [
                "user@example.com",
                "invalid-format",
                "user@example.com"  # Duplicate
            ],
            "smtp_check": False
        }

        response = self.client.post(
            "/api/verify",
            data=json.dumps(payload),
            content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total"], 3)
        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["total"], 3)
        self.assertEqual(len(data["results"]), 3)

        # First address should be deliverable/valid
        self.assertEqual(data["results"][0]["status_category"], "valid")
        # Second address should bounce/invalid (syntax invalid)
        self.assertEqual(data["results"][1]["status_category"], "invalid")
        # Third address (duplicate) should match first
        self.assertEqual(data["results"][2]["status_category"], "valid")

    def test_api_verify_empty_emails_list(self):
        """Empty emails list should return 400 Bad Request."""
        payload = {"emails": []}
        response = self.client.post(
            "/api/verify",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("cannot be empty", data["error"])

    def test_api_verify_missing_emails_field(self):
        """Missing emails key should return 400 Bad Request."""
        payload = {"invalid_key": []}
        response = self.client.post(
            "/api/verify",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("Missing required 'emails' field", data["error"])

    def test_api_verify_non_json_payload(self):
        """Non-JSON request should return 400 Bad Request."""
        response = self.client.post(
            "/api/verify",
            data="raw text string",
            content_type="text/plain"
        )
        self.assertEqual(response.status_code, 400)

    def test_api_verify_exceeds_max_limit(self):
        """Submitting > 100 emails should return 400 Bad Request."""
        payload = {"emails": [f"user{i}@test.com" for i in range(101)]}
        response = self.client.post(
            "/api/verify",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("exceeds maximum limit", data["error"])

    def test_api_404_not_found(self):
        """Unknown API path returns JSON 404 error."""
        response = self.client.get("/api/unknown_route")
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertFalse(data["success"])


if __name__ == "__main__":
    unittest.main()
