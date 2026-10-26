import urllib.request
import json
import sys

BASE_URL = 'https://emailcheck-7c9y.onrender.com'

def test_live():
    print(f"=== Testing EmailCheck v2.1 Live Deployment at {BASE_URL} ===\n")

    # 1. Test GET /health
    health_url = f"{BASE_URL}/health"
    print(f"1. Checking {health_url}...")
    try:
        req = urllib.request.Request(health_url, headers={'User-Agent': 'EmailCheckLiveTest/2.1'})
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f"   Status: {resp.status} - Version: {data.get('version')} - Stages: {data.get('pipeline_stage_count')}")
            assert data.get('status') == 'healthy', "Health check failed"
            assert data.get('version') == '2.1.0', f"Expected v2.1.0, got {data.get('version')}"
            assert data.get('pipeline_stage_count') == 7, "Expected 7 pipeline stages"
            print("   [PASS] Health check passed (v2.1.0, 7 stages verified).\n")
    except Exception as e:
        print(f"   [FAIL] Health check failed: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Test GET / for LaTeX arrow regression
    print(f"2. Inspecting HTML for LaTeX arrow leakages at {BASE_URL}/...")
    try:
        req = urllib.request.Request(f"{BASE_URL}/", headers={'User-Agent': 'EmailCheckLiveTest/2.1'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8')
            assert r'$\rightarrow$' not in html, "Found literal $\\rightarrow$ in HTML!"
            assert r'\rightarrow' not in html, "Found literal \\rightarrow in HTML!"
            assert 'Non-Invasive Verification Pipeline' in html, "Missing clean banner"
            assert 'Domain Diagnostics' in html, "Missing Domain Diagnostics tab"
            assert 'Verification History' in html, "Missing Verification History tab"
            print("   [PASS] Zero LaTeX artifacts in live HTML. Exact clean banner verified.\n")
    except Exception as e:
        print(f"   [FAIL] HTML regression check failed: {e}", file=sys.stderr)
        sys.exit(1)

    # 3. Test POST /api/domain (Domain Diagnostics)
    domain_url = f"{BASE_URL}/api/domain"
    print(f"3. Testing Domain Diagnostics endpoint at {domain_url}...")
    try:
        req_data = json.dumps({'domain': 'google.com'}).encode('utf-8')
        req = urllib.request.Request(domain_url, data=req_data, headers={'Content-Type': 'application/json', 'User-Agent': 'EmailCheckLiveTest/2.1'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            assert res.get('success') is True
            assert res.get('can_receive_email') is True
            print(f"   [PASS] google.com -> {res.get('verdict')} ({len(res.get('mx_records', []))} MX records)")

        # Test disposable domain
        req_data = json.dumps({'domain': 'mailinator.com'}).encode('utf-8')
        req = urllib.request.Request(domain_url, data=req_data, headers={'Content-Type': 'application/json', 'User-Agent': 'EmailCheckLiveTest/2.1'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            assert res.get('is_disposable') is True
            print(f"   [PASS] mailinator.com -> Disposable correctly identified (is_disposable={res.get('is_disposable')})\n")
    except Exception as e:
        print(f"   [FAIL] Domain diagnostics test failed: {e}", file=sys.stderr)
        sys.exit(1)

    # 4. Test POST /api/verify
    verify_url = f"{BASE_URL}/api/verify"
    print(f"4. Testing Batch Verification at {verify_url}...")
    payload = {
        'emails': [
            'bad..syntax@@domain',
            'user@nonexistent-domain-xyz987654321.org',
            'test@mailinator.com',
            'support@github.com'
        ]
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(verify_url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'EmailCheckLiveTest/2.1'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            print("   Summary:", json.dumps(result.get('summary', {})))
            for item in result.get('results', []):
                print(f"   * {item.get('email')} -> [{item.get('classification')}] ({item.get('reason')})")
            print("\n[PASS] Live verification pipeline functioning successfully!")
    except Exception as e:
        print(f"   [FAIL] Verification test failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    test_live()
