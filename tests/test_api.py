"""
Integration tests for EmailCheck Flask endpoints (app.py).
Tests REST API validation, responses, error handlers, and rate limiting.
"""

import unittest
from unittest.mock import patch
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
        """Health check endpoint should return healthy status."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "EmailCheck")
        self.assertIn("smtp_outbound_available", data)

    @patch("verifier.check_domain_dns")
    def test_api_verify_valid_batch(self, mock_dns):
        """POST /api/verify with valid input list returns structured results."""
        mock_dns.return_value = {
            "domain": "example.com",
            "domain_status": "exists",
            "mx_status": "mx_found",
            "mx_records": ["mail.example.com (priority 10)"],
            "primary_mx": "mail.example.com",
            "error": None
        }

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

        # First address should be delivered
        self.assertEqual(data["results"][0]["classification"], "Likely to be Delivered")
        # Second address should bounce (syntax invalid)
        self.assertEqual(data["results"][1]["classification"], "Likely to Bounce")
        # Third address (duplicate) should match first
        self.assertEqual(data["results"][2]["classification"], "Likely to be Delivered")

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
