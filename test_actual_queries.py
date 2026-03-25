#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test actual VIN submission and API calls to promising sources.
"""

import httpx
import json
from bs4 import BeautifulSoup
import re

TEST_VIN = "WBADT43452G808797"  # Real BMW VIN

def test_vin_info_com():
    """Test vin-info.com with actual VIN submission"""
    print(f"\n{'='*80}")
    print("Testing: vin-info.com")
    print('='*80)

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        # First, get the form structure
        print("Step 1: Fetching form structure...")
        response = client.get("https://vin-info.com/en/", headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the form
        form = soup.find('form', method='POST')
        if not form:
            print("[WARN] No POST form found")
            return

        # Extract form data
        form_data = {}
        for inp in form.find_all(['input', 'select', 'textarea']):
            name = inp.get('name')
            value = inp.get('value', '')
            if name:
                form_data[name] = value

        print(f"  Found {len(form_data)} form fields")
        print(f"  Fields: {list(form_data.keys())}")

        # Now submit with VIN
        print(f"\nStep 2: Submitting VIN '{TEST_VIN}'...")
        form_data['form_fields[wdgvininput]'] = TEST_VIN

        try:
            response = client.post(
                "https://vin-info.com/en/",
                data=form_data,
                headers=headers,
                follow_redirects=True
            )

            print(f"  Response Status: {response.status_code}")
            print(f"  Content Length: {len(response.text)} bytes")

            # Check what we got back
            if "damage" in response.text.lower() or "accident" in response.text.lower():
                print("  [FOUND] Damage/accident data in response")

                # Try to extract data
                soup = BeautifulSoup(response.text, 'html.parser')
                results = soup.find_all(class_=re.compile('result|damage|accident|history', re.I))
                if results:
                    print(f"  [DATA] Found {len(results)} result sections:")
                    for i, result in enumerate(results[:3]):
                        text = result.get_text(strip=True)[:100]
                        print(f"    Result {i+1}: {text}...")
            else:
                print("  [NO DATA] No damage/accident data returned")

            # Look for JSON data in page
            scripts = soup.find_all('script', type='application/json')
            if scripts:
                print(f"\n  JSON data blocks found: {len(scripts)}")
                for i, script in enumerate(scripts[:2]):
                    try:
                        data = json.loads(script.string)
                        print(f"    Block {i+1} keys: {list(data.keys())[:5]}")
                    except:
                        pass

        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {str(e)[:100]}")


def test_carvertical_com():
    """Test carvertical.com form submission"""
    print(f"\n{'='*80}")
    print("Testing: carvertical.com")
    print('='*80)

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        print("Step 1: Fetching page structure...")
        response = client.get("https://www.carvertical.com/", headers=headers)

        # Look for API endpoints
        print("Step 2: Searching for API endpoints...")
        api_pattern = r'"api[^"]*":"([^"]+)"'
        matches = re.findall(api_pattern, response.text, re.I)
        if matches:
            print(f"  Found {len(matches[:5])} potential API paths:")
            for match in matches[:5]:
                print(f"    {match}")

        # Look for fetch calls or AJAX
        fetch_pattern = r'fetch\([\'"]([^\'"]+)'
        fetch_matches = re.findall(fetch_pattern, response.text)
        if fetch_matches:
            print(f"\n  Found {len(fetch_matches[:5])} fetch calls:")
            for match in fetch_matches[:5]:
                print(f"    {match}")

        # Try to find the form and submit
        print(f"\nStep 3: Looking for search form...")
        soup = BeautifulSoup(response.text, 'html.parser')
        forms = soup.find_all('form')
        print(f"  Found {len(forms)} forms")

        for i, form in enumerate(forms[:2]):
            method = form.get('method', 'GET').upper()
            action = form.get('action', 'current page')
            print(f"\n  Form {i+1}:")
            print(f"    Method: {method}")
            print(f"    Action: {action}")

            inputs = form.find_all('input')
            for inp in inputs:
                print(f"    Input: {inp.get('name')} (type={inp.get('type')})")

        # Try submitting via form
        print(f"\nStep 4: Attempting form submission...")
        form = soup.find('form')
        if form:
            form_data = {}
            for inp in form.find_all('input'):
                name = inp.get('name')
                if name:
                    form_data[name] = TEST_VIN

            print(f"  Submitting: {form_data}")

            try:
                action = form.get('action', 'https://www.carvertical.com/')
                method = form.get('method', 'GET').upper()

                if method == 'POST':
                    r = client.post(action, data=form_data, headers=headers)
                else:
                    r = client.get(action, params=form_data, headers=headers)

                print(f"  Response: {r.status_code}")
                if "damage" in r.text.lower():
                    print("  [SUCCESS] Damage data returned!")
                else:
                    print("  [INFO] Response received but unclear if data returned")

            except Exception as e:
                print(f"  [ERROR] {type(e).__name__}: {str(e)[:80]}")


def test_direct_api():
    """Test if these services expose direct API endpoints"""
    print(f"\n{'='*80}")
    print("Testing: Direct API Endpoints")
    print('='*80)

    # Common API patterns for VIN decoders
    endpoints = [
        ("CarVertical API", "https://api.carvertical.com/v1/reports", "POST"),
        ("autoDNA API", "https://api.autodna.com/v1/report", "POST"),
        ("vin-info API", "https://vin-info.com/api/check", "POST"),
    ]

    with httpx.Client(timeout=10.0) as client:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json"
        }

        for name, url, method in endpoints:
            print(f"\nTesting: {name}")
            print(f"  URL: {url}")

            try:
                if method == "POST":
                    r = client.post(url, json={"vin": TEST_VIN}, headers=headers)
                else:
                    r = client.get(f"{url}?vin={TEST_VIN}", headers=headers)

                print(f"  Status: {r.status_code}")

                if r.status_code == 200:
                    print(f"  [SUCCESS] Endpoint accessible!")
                    try:
                        data = r.json()
                        print(f"  Keys returned: {list(data.keys())[:10]}")
                    except:
                        print(f"  Content type: {r.headers.get('content-type')}")
                elif r.status_code == 401:
                    print(f"  [AUTH] Requires authentication (API key)")
                elif r.status_code == 404:
                    print(f"  [NOT FOUND] Endpoint doesn't exist")
                else:
                    print(f"  Status: {r.status_code}")

            except Exception as e:
                print(f"  [ERROR] {type(e).__name__}: {str(e)[:80]}")


if __name__ == "__main__":
    print("EU Vehicle History Sources - Query Testing")
    print("=" * 80)

    test_vin_info_com()
    test_carvertical_com()
    test_direct_api()

    print(f"\n{'='*80}")
    print("Testing complete")
