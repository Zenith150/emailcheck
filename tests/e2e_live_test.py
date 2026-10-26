"""
End-to-end live testing script for EmailCheck server (v2.0).
Starts local server, exercises health check and multi-stage verification pipeline,
verifying disposable filtering, NXDOMAIN, and RFC syntax without port 25.
"""

import os
import sys
import time
import json
import urllib.request
import subprocess

def run_test():
    env = os.environ.copy()
    env["PORT"] = "5005"
    env["FLASK_DEBUG"] = "0"
    env["EMAIL_VERIFICATION_PROVIDER"] = "none"

    print("Starting EmailCheck test server on port 5005...")
    proc = subprocess.Popen([sys.executable, "app.py"], env=env)
    time.sleep(2.5)

    try:
        # Test 1: Health check
        print("\n--- Testing GET /health ---")
        req = urllib.request.Request("http://127.0.0.1:5005/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"Health Response Code: {resp.status}")
            print(f"Health Data: {json.dumps(data, indent=2)}")
            assert resp.status == 200
            assert data["status"] == "healthy"
            assert "provider" in data

        # Test 2: Multi-stage email verification batch
        print("\n--- Testing POST /api/verify ---")
        payload = {
            "emails": [
                "support@github.com",
                "test.user@mailinator.com",
                "malformed..syntax@@domain",
                "service@nonexistent-fake-domain-xyz98741.invalid",
                "support@github.com"  # Duplicate
            ],
            "smtp_check": False
        }
        req = urllib.request.Request(
            "http://127.0.0.1:5005/api/verify",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            print(f"Verify Response Code: {resp.status}")
            print(f"Total processed: {data.get('total')}")
            print(f"Summary: {json.dumps(data.get('summary'), indent=2)}")
            for item in data.get("results", []):
                email = item.get("email")
                classification = item.get("classification")
                is_disp = item.get("is_disposable")
                reason = item.get("reason")
                print(f"  * {email} -> [{classification}] (Disposable: {is_disp}) : {reason}")

            assert resp.status == 200
            assert data.get("total") == 5
            # mailinator should be flagged disposable
            assert data["results"][1]["is_disposable"] is True
            assert data["results"][1]["status_category"] == "risky"
            # malformed should be invalid
            assert data["results"][2]["status_category"] == "invalid"
            # nonexistent should be invalid
            assert data["results"][3]["status_category"] == "invalid"

        print("\n=== All live end-to-end tests PASSED successfully! ===")

    finally:
        print("Stopping test server...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    run_test()
