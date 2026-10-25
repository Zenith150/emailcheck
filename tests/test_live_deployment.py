"""
Test live deployed EmailCheck on Render.
Verifies GET /, GET /health, and POST /api/verify.
"""

import urllib.request
import json
import sys

BASE_URL = "https://emailcheck-7c9y.onrender.com"

def test_live():
    print(f"=== Testing Live Deployed Service: {BASE_URL} ===\n")

    # 1. GET /
    print("1. Testing GET / (Homepage)... (allowing up to 50s for potential Render cold start)")
    req = urllib.request.Request(BASE_URL, headers={"User-Agent": "EmailCheckTester/1.0"})
    with urllib.request.urlopen(req, timeout=50) as resp:
        html = resp.read().decode("utf-8")
        print(f"   Status Code: {resp.status}")
        assert resp.status == 200
        assert "EmailCheck" in html
        print("   Homepage loaded successfully with title 'EmailCheck'.\n")

    # 2. GET /health
    print("2. Testing GET /health...")
    req = urllib.request.Request(f"{BASE_URL}/health", headers={"User-Agent": "EmailCheckTester/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        health_data = json.loads(resp.read().decode("utf-8"))
        print(f"   Status Code: {resp.status}")
        print(f"   Health Data: {json.dumps(health_data, indent=2)}")
        assert resp.status == 200
        assert health_data.get("status") == "healthy"
        print("   Health check confirmed healthy.\n")

    # 3. POST /api/verify
    print("3. Testing POST /api/verify...")
    test_batch = [
        "support@github.com",
        "contact@google.com",
        "invalid..syntax@@domain",
        "service@nonexistent-fake-domain-xyz98741.invalid"
    ]
    payload = json.dumps({"emails": test_batch, "smtp_check": False}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/verify",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "EmailCheckTester/1.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        print(f"   Status Code: {resp.status}")
        print(f"   Total addresses: {res.get('total')}")
        print(f"   Summary: {json.dumps(res.get('summary'), indent=2)}")
        for item in res.get("results", []):
            email = item.get("email")
            cls = item.get("classification")
            reason = item.get("reason")
            print(f"   * {email} -> [{cls}] {reason}")

        assert resp.status == 200
        assert res.get("success") is True
        assert res.get("summary", {}).get("likely_to_deliver") == 2
        assert res.get("summary", {}).get("likely_to_bounce") == 2
        print("\n=== All live deployed tests PASSED successfully! ===")

if __name__ == "__main__":
    test_live()
