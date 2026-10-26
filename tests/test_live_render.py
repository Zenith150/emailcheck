import urllib.request
import json
import sys

def test_live():
    url = 'https://emailcheck-7c9y.onrender.com/api/verify'
    payload = {
        'emails': [
            'bad..syntax@@domain',
            'user@nonexistent-domain-xyz987654321.org',
            'test@mailinator.com',
            'support@github.com'
        ]
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'EmailCheckLiveTest/2.0'
        }
    )
    
    print(f"Testing live verification endpoint: {url}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"HTTP Status: {resp.status}")
            result = json.loads(resp.read().decode('utf-8'))
            print("Response Summary:", json.dumps(result.get('summary', {}), indent=2))
            print("\nDetailed Address Classifications:")
            for item in result.get('results', []):
                email = item.get('email')
                classification = item.get('classification')
                syntax = item.get('syntax_valid')
                domain_status = item.get('domain_status')
                mx_status = item.get('mx_status')
                disposable = item.get('disposable')
                recipient_check = item.get('recipient_check', {})
                reason = item.get('reason')
                print(f" * {email} -> [{classification}]")
                print(f"   Syntax: {syntax} | Domain: {domain_status} | MX: {mx_status} | Disposable: {disposable}")
                print(f"   Recipient Status: {recipient_check.get('status')} ({recipient_check.get('details')})")
                print(f"   Reason: {reason}\n")
    except Exception as e:
        print(f"Failed to test live endpoint: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    test_live()
