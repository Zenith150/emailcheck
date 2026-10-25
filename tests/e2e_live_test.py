"""
End-to-end live testing script for EmailCheck server.
Starts server, sends requests to /health and /api/verify, validates responses, and exits.
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

        # Test 2: Live email verification batch
        print("\n--- Testing POST /api/verify ---")
        payload = {
            "emails": [
                "alex@gmail.com",
                "malformed..syntax@@domain",
                "test@nonexistent-fake-domain-xyz987654321.org",
                "alex@gmail.com"  # Duplicate
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
                reason = item.get("reason")
                print(f"  * {email} -> [{classification}] : {reason}")

            assert resp.status == 200
            assert data["summary"]["likely_to_deliver"] == 2
            assert data["summary"]["likely_to_bounce"] == 2
            assert data["summary"]["total"] == 4

        print("\n=== All live end-to-end tests PASSED successfully! ===")

    finally:
        print("Stopping test server...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    run_test()
