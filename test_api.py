import requests
import json
import sys

BASE_URL = "http://localhost:5000"

ENDPOINTS = [
    ("GET", "/api/health"),
    ("GET", "/api/today"),
    ("GET", "/api/projects"),
    ("GET", "/api/employees"),
    ("GET", "/api/certifications"),
    ("GET", "/api/cert-types"),
    ("GET", "/api/sign-ins/today"),
    ("GET", "/api/rfis"),
    ("GET", "/api/drops"),
    ("GET", "/api/permits"),
    ("GET", "/api/documents"),
    ("GET", "/api/toolbox-talks"),
    ("GET", "/api/meetings"),
    ("GET", "/api/action-items"),
    ("GET", "/api/site-closures"),
    ("GET", "/api/lookahead"),
    ("GET", "/api/dob-references"),
]

def test_endpoint(method, path):
    try:
        url = f"{BASE_URL}{path}"
        resp = requests.request(method, url, timeout=5)
        status = resp.status_code
        
        try:
            data = resp.json()
            count = data.get('meta', {}).get('count', 'N/A')
            result = "PASS" if status == 200 else "FAIL"
        except:
            result = "FAIL"
            count = "N/A"
        
        print(f"{result:4} | {status:3} | {method:4} {path:35} | count={count}")
        return result == "PASS"
    except requests.exceptions.ConnectionError:
        print(f"FAIL | ERR | {method:4} {path:35} | Connection refused")
        return False
    except Exception as e:
        print(f"FAIL | ERR | {method:4} {path:35} | {str(e)[:30]}")
        return False

if __name__ == '__main__':
    print("\nTesting Flask API Endpoints")
    print("=" * 95)
    
    passed = 0
    failed = 0
    
    for method, path in ENDPOINTS:
        if test_endpoint(method, path):
            passed += 1
        else:
            failed += 1
    
    print("=" * 95)
    print(f"Results: {passed} passed, {failed} failed")
    
    sys.exit(0 if failed == 0 else 1)
