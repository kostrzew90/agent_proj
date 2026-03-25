#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test EU vehicle history sources for:
1. Cloudflare presence
2. Free tier accessibility
3. Data returned (damage/accident history)
"""

import httpx
import time
import sys
from urllib.parse import urlparse

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Test VINs (European format examples)
TEST_VIN = "WBADT43452G808797"  # BMW
TEST_PLATE_DE = "B-DK 9999"  # German plate format
TEST_PLATE_PL = "DW 12345"   # Polish plate format
TEST_PLATE_HU = "ABC-123"     # Hungarian plate format

sources = [
    {
        "name": "vin-info.com",
        "url": "https://vin-info.com/en/free-vin-check/",
        "method": "GET",
        "test_data": {"vin": TEST_VIN},
        "input_type": "VIN"
    },
    {
        "name": "autodna.com",
        "url": "https://www.autodna.com/vin-decoder",
        "method": "GET",
        "test_data": {"vin": TEST_VIN},
        "input_type": "VIN"
    },
    {
        "name": "carvertical.com",
        "url": "https://www.carvertical.com/check/",
        "method": "GET",
        "test_data": {"vin": TEST_VIN},
        "input_type": "VIN"
    },
    {
        "name": "otomoto.pl",
        "url": "https://www.otomoto.pl/auto-historia/",
        "method": "GET",
        "test_data": {"plate": TEST_PLATE_PL},
        "input_type": "License Plate"
    },
    {
        "name": "bezwypadkowy.com",
        "url": "https://bezwypadkowy.com/",
        "method": "GET",
        "test_data": {"vin": TEST_VIN},
        "input_type": "VIN"
    },
    {
        "name": "check24.de",
        "url": "https://www.check24.de/unfallwagen-check/",
        "method": "GET",
        "test_data": {"plate": TEST_PLATE_DE},
        "input_type": "License Plate"
    },
    {
        "name": "totalcar.hu",
        "url": "https://totalcar.hu/vin/",
        "method": "GET",
        "test_data": {"vin": TEST_VIN},
        "input_type": "VIN"
    }
]

def check_cloudflare(headers: dict) -> bool:
    """Check if response indicates Cloudflare protection"""
    cf_indicators = [
        "cloudflare" in str(headers).lower(),
        headers.get("Server", "").lower() == "cloudflare",
        headers.get("CF-Ray") is not None,
        headers.get("X-Frame-Options") is not None and "cloudflare" in str(headers).lower(),
    ]
    return any(cf_indicators)

def test_source(source: dict):
    """Test a single source"""
    print(f"\n{'='*70}")
    print(f"Testing: {source['name']}")
    print(f"URL: {source['url']}")
    print(f"Input Type: {source['input_type']}")
    print('='*70)

    try:
        # Use httpx with a regular browser user-agent
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(source['url'], headers=headers)

        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.text)} bytes")

        # Check for Cloudflare
        cf_detected = check_cloudflare(response.headers)
        print(f"Cloudflare Detected: {'YES [WARNING]' if cf_detected else 'NO [SAFE]'}")

        # Check response headers
        print(f"\nKey Headers:")
        key_headers = ["Server", "CF-Ray", "X-Frame-Options", "X-Content-Type-Options", "Set-Cookie"]
        for header in key_headers:
            if header in response.headers:
                print(f"  {header}: {response.headers[header][:100]}")

        # Look for common patterns in HTML
        text_lower = response.text.lower()

        patterns = {
            "Has VIN/Plate input form": any(p in text_lower for p in ["vin", "plate", "registration", "license"]),
            "Shows damage/accident data": any(p in text_lower for p in ["accident", "damage", "crashed", "collision", "history", "reported", "incident", "wreck"]),
            "Free tier available": any(p in text_lower for p in ["free", "kostenlos", "ingyenes", "darmow", "bez opłat"]),
            "Requires registration": any(p in text_lower for p in ["register", "sign up", "create account", "login", "zaloguj"]),
        }

        print(f"\nContent Analysis:")
        for pattern, found in patterns.items():
            status = '[FOUND]' if found else '[NOT FOUND]'
            print(f"  {pattern}: {status}")

        # Show snippet of title/description
        if "<title>" in response.text:
            title = response.text.split("<title>")[1].split("</title>")[0][:100]
            print(f"\nPage Title: {title}")

        # Attempt to identify input method
        if "?vin=" in response.text or "?plate=" in response.text or "search" in text_lower:
            print(f"\nInput Method: Appears to be query parameter or form-based")

        status = 'PROCEED WITH CAUTION (CF detected)' if cf_detected else 'SAFE TO SCRAPE'
        print(f"\n[REACHABLE] Status: {status}")

    except httpx.ConnectError:
        print(f"[ERROR] CONNECTION ERROR - Cannot reach endpoint")
    except httpx.TimeoutException:
        print(f"[ERROR] TIMEOUT - Server not responding within 10s")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {str(e)[:100]}")

if __name__ == "__main__":
    print("EU Vehicle History Sources Assessment")
    print("Testing for CF, accessibility, and data quality\n")

    for source in sources:
        test_source(source)
        time.sleep(1)  # Be respectful with requests

    print(f"\n{'='*70}")
    print("Assessment Complete")
    print('='*70)
