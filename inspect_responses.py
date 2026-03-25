#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inspect actual responses from promising sources to understand data structure.
Also test additional Polish sources.
"""

import httpx
import json
from bs4 import BeautifulSoup
import re

TEST_VIN = "WBADT43452G808797"
TEST_PLATE_PL = "DW 12345"
TEST_PLATE_DE = "B-DK 9999"

def inspect_carvertical():
    """Inspect CarVertical response in detail"""
    print(f"\n{'='*80}")
    print("INSPECTION: CarVertical.com")
    print('='*80)

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        print("Submitting VIN via form...")
        response = client.get(
            "https://www.carvertical.com/",
            params={"identifier": TEST_VIN},
            headers=headers
        )

        print(f"Status: {response.status_code}")

        # Extract useful information
        soup = BeautifulSoup(response.text, 'html.parser')

        # Look for damage/accident mentions
        keywords = ["damage", "accident", "history", "crashed", "wreck", "incident"]
        for keyword in keywords:
            pattern = re.compile(keyword, re.I)
            matches = soup.find_all(string=pattern)
            if matches:
                print(f"\n[{keyword.upper()}] Found {len(matches)} mentions:")
                for match in matches[:3]:
                    parent = match.parent.get_text(strip=True)[:100]
                    print(f"  {parent}...")

        # Look for structured data (JSON-LD, etc.)
        json_scripts = soup.find_all('script', type='application/json')
        print(f"\nJSON blocks: {len(json_scripts)}")

        # Look for data in divs and spans
        data_attrs = soup.find_all(attrs={"data-test": True})
        if data_attrs:
            print(f"\nData attributes found: {len(data_attrs[:5])}")
            for elem in data_attrs[:5]:
                test_id = elem.get('data-test')
                text = elem.get_text(strip=True)[:60]
                print(f"  {test_id}: {text}")

        # Check for price/quote info (which might require login)
        pricing = soup.find_all(string=re.compile("price|cost|report|premium", re.I))
        if pricing:
            print(f"\nPricing mentions: {len(pricing)}")
            for p in pricing[:3]:
                print(f"  {p.get_text()[:80] if hasattr(p, 'get_text') else str(p)[:80]}")

        # Look for what's free vs paid
        free_mentions = soup.find_all(string=re.compile("free", re.I))
        if free_mentions:
            print(f"\nFree mentions: {len(free_mentions)}")
            for f in free_mentions[:3]:
                context = f.parent.get_text(strip=True)[:100] if hasattr(f, 'parent') else str(f)[:100]
                print(f"  {context}...")


def test_polish_sources():
    """Test additional Polish sources"""
    print(f"\n{'='*80}")
    print("TESTING: Polish Vehicle History Sources")
    print('='*80)

    sources = [
        ("historia.otomoto.pl", "https://historia.otomoto.pl/"),
        ("samochody.net.pl", "https://www.samochody.net.pl/historia/"),
        ("cena.auto.pl", "https://cena.auto.pl/"),
    ]

    with httpx.Client(timeout=15.0) as client:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        for name, url in sources:
            print(f"\nTesting: {name}")
            try:
                response = client.get(url, headers=headers, follow_redirects=True)
                print(f"  Status: {response.status_code}")

                # Check for CF
                if "cloudflare" in response.text.lower():
                    print(f"  [BLOCKED] Cloudflare detected")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')

                # Look for forms
                forms = soup.find_all('form')
                print(f"  Forms: {len(forms)}")

                if forms:
                    form = forms[0]
                    inputs = form.find_all('input')
                    print(f"  Input fields:")
                    for inp in inputs[:5]:
                        name = inp.get('name')
                        itype = inp.get('type', 'text')
                        print(f"    - {name} ({itype})")

                # Check for damage/accident info
                has_damage = any(kw in response.text.lower() for kw in ["wypadek", "uszkodzenie", "damage", "accident"])
                print(f"  Damage/Accident data: {'YES' if has_damage else 'NO'}")

                print(f"  [REACHABLE]")

            except Exception as e:
                print(f"  [ERROR] {type(e).__name__}")


def search_free_vin_apis():
    """Search for known free VIN decoder APIs"""
    print(f"\n{'='*80}")
    print("RESEARCH: Known Free VIN Decoder APIs")
    print('='*80)

    # These are known to provide free VIN decoding
    free_apis = [
        ("NHTSA API", "https://vpic.nhtsa.dot.gov/api/", "US only"),
        ("VIN Decoder API", "https://api.vindecoder.eu/", "EU"),
        ("VIN-Info API", "https://vin-info.com/api/", "EU/Free"),
    ]

    print("\nKnown Free APIs:")
    for name, url, region in free_apis:
        print(f"  {name}")
        print(f"    URL: {url}")
        print(f"    Region: {region}")

    print("\nNote: NHTSA provides free API with no authentication")
    print("  - VehicleDecoder: decode VIN to make/model")
    print("  - Recalls: get safety recalls")
    print("  - Complaints: get complaint history")


def test_vin_decoder_eu():
    """Test the VIN Decoder EU API"""
    print(f"\n{'='*80}")
    print("TESTING: VIN Decoder EU API")
    print('='*80)

    with httpx.Client(timeout=10.0) as client:
        # Try common endpoints
        endpoints = [
            ("Basic decode", f"https://api.vindecoder.eu/v1/decode/{TEST_VIN}"),
            ("With report", f"https://api.vindecoder.eu/v1/decode/{TEST_VIN}?include=damage"),
        ]

        for desc, url in endpoints:
            print(f"\n{desc}: {url}")
            try:
                response = client.get(url)
                print(f"  Status: {response.status_code}")

                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"  [SUCCESS] Data returned")
                        print(f"  Keys: {list(data.keys())[:20]}")
                    except:
                        print(f"  [RECEIVED] Non-JSON response: {response.text[:100]}")
                elif response.status_code == 401:
                    print(f"  [AUTH] Requires API key")
                elif response.status_code == 404:
                    print(f"  [NOT FOUND] Endpoint invalid")

            except Exception as e:
                print(f"  [ERROR] {type(e).__name__}: {str(e)[:80]}")


if __name__ == "__main__":
    print("EU Vehicle History - Deep Inspection")
    print("=" * 80)

    inspect_carvertical()
    test_polish_sources()
    search_free_vin_apis()
    test_vin_decoder_eu()

    print(f"\n{'='*80}")
    print("Inspection complete")
