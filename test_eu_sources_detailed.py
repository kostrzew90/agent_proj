#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detailed investigation of EU vehicle history sources.
Tests actual API endpoints and form submission capabilities.
"""

import httpx
import json
from bs4 import BeautifulSoup
import time

TEST_VIN = "WBADT43452G808797"
TEST_PLATE_PL = "DW 12345"

def investigate_source(name, base_url, input_type="VIN"):
    """Investigate a source in detail"""
    print(f"\n{'='*80}")
    print(f"INVESTIGATING: {name}")
    print(f"{'='*80}")
    print(f"URL: {base_url}")
    print(f"Input Type: {input_type}\n")

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            # Get the main page
            response = client.get(base_url, headers=headers)
            print(f"Status: {response.status_code}")

            # Check for Cloudflare
            if response.status_code == 403 or "cloudflare" in response.text.lower():
                print("[BLOCKED] Cloudflare protection detected\n")
                return

            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for forms
            forms = soup.find_all('form')
            print(f"Forms found: {len(forms)}")

            if forms:
                for i, form in enumerate(forms[:2]):  # Check first 2 forms
                    print(f"\nForm {i+1}:")
                    print(f"  Action: {form.get('action', 'N/A')}")
                    print(f"  Method: {form.get('method', 'GET').upper()}")

                    inputs = form.find_all(['input', 'select', 'textarea'])
                    print(f"  Fields:")
                    for inp in inputs:
                        field_name = inp.get('name', 'unknown')
                        field_type = inp.get('type', inp.name)
                        print(f"    - {field_name} ({field_type})")

            # Look for API endpoints in JavaScript
            scripts = soup.find_all('script')
            api_hints = []
            for script in scripts:
                if script.string:
                    if 'api' in script.string.lower() or 'fetch' in script.string.lower():
                        # Extract potential API URLs
                        if 'http' in script.string.lower():
                            lines = [line.strip() for line in script.string.split('\n') if 'api' in line.lower() and 'http' in line.lower()]
                            api_hints.extend(lines[:3])

            if api_hints:
                print(f"\nPotential API endpoints found in JS:")
                for hint in api_hints:
                    print(f"  {hint[:100]}...")

            # Look for data attributes
            data_divs = soup.find_all(attrs={"data-api": True})
            if data_divs:
                print(f"\nData attributes found:")
                for div in data_divs[:3]:
                    for key, val in div.attrs.items():
                        if key.startswith('data-'):
                            print(f"  {key}: {str(val)[:80]}")

            # Look for mentions of "free", "damage", "accident"
            text = response.text.lower()
            keywords = {
                "Free access": "free" in text or "kostenlos" in text,
                "Damage history": "damage" in text or "accident" in text or "crashed" in text or "schaden" in text,
                "Registration required": "login" in text or "register" in text or "zaloguj" in text,
            }

            print(f"\nFeatures mentioned on page:")
            for feature, found in keywords.items():
                status = "[YES]" if found else "[NO]"
                print(f"  {feature}: {status}")

            print(f"\n[OK] Page reachable, no Cloudflare")

    except httpx.ConnectError as e:
        print(f"[ERROR] Cannot connect: {e}")
    except httpx.TimeoutException:
        print(f"[ERROR] Timeout connecting")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {str(e)[:100]}")

# List of sources to investigate
sources = [
    ("vin-info.com", "https://vin-info.com/en/", "VIN"),
    ("autoDNA", "https://www.autodna.com/", "VIN"),
    ("CarVertical", "https://www.carvertical.com/", "VIN"),
    ("Otomoto.pl", "https://www.otomoto.pl/", "Plate"),
    ("Check24.de", "https://www.check24.de/", "Plate"),
    ("TotalCar.hu", "https://totalcar.hu/", "VIN"),
]

print("EU Vehicle History Sources - Detailed Investigation")
print("=" * 80)

for name, url, input_type in sources:
    investigate_source(name, url, input_type)
    time.sleep(1)

print(f"\n{'='*80}")
print("Investigation complete")
