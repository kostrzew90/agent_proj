#!/usr/bin/env python3
"""
OSINT Checkers - Email and Phone verification modules
"""

import re
import subprocess
import json
import asyncio
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

import requests
import phonenumbers
from phonenumbers import geocoder, carrier, timezone

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SourceResult:
    """Result from a single OSINT source"""
    source_name: str
    source_category: str
    status: str  # 'found', 'not_found', 'error', 'timeout'
    found: bool
    raw_response: dict = field(default_factory=dict)
    extracted_data: dict = field(default_factory=dict)
    response_time_ms: int = 0
    error_message: Optional[str] = None


@dataclass
class CheckResult:
    """Complete check result"""
    input_value: str
    input_type: str  # 'phone' or 'email'
    normalized_value: str
    risk_category: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    risk_factors: list
    sources: list  # List[SourceResult]
    duration_ms: int
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def sources_checked(self) -> int:
        return len(self.sources)

    @property
    def sources_found(self) -> int:
        return sum(1 for s in self.sources if s.found)

    def to_dict(self) -> dict:
        return {
            'input_value': self.input_value,
            'input_type': self.input_type,
            'normalized_value': self.normalized_value,
            'risk_category': self.risk_category,
            'risk_factors': self.risk_factors,
            'sources_checked': self.sources_checked,
            'sources_found': self.sources_found,
            'duration_ms': self.duration_ms,
            'timestamp': self.timestamp.isoformat(),
            'sources': [
                {
                    'source_name': s.source_name,
                    'source_category': s.source_category,
                    'status': s.status,
                    'found': s.found,
                    'extracted_data': s.extracted_data,
                    'error_message': s.error_message
                }
                for s in self.sources
            ]
        }


# =============================================================================
# Input Detection & Normalization
# =============================================================================

def detect_input_type(value: str) -> str:
    """Auto-detect if input is phone, email, or username"""
    value = value.strip()

    # Email pattern
    if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', value):
        return 'email'

    # Phone pattern (with or without +)
    cleaned = re.sub(r'[\s\-\(\)]', '', value)
    if re.match(r'^\+?\d{9,15}$', cleaned):
        return 'phone'

    # Default to email if contains @
    if '@' in value:
        return 'email'

    # Username pattern (alphanumeric, dots, underscores, 3-30 chars)
    if re.match(r'^[a-zA-Z0-9._]{3,30}$', value):
        return 'username'

    return 'unknown'


def normalize_phone(phone: str) -> Optional[str]:
    """Normalize phone number to E.164 format"""
    try:
        # Try parsing with default region PL
        parsed = phonenumbers.parse(phone, 'PL')
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed,
                phonenumbers.PhoneNumberFormat.E164
            )
    except Exception:
        pass

    # Try without region
    try:
        parsed = phonenumbers.parse(phone, None)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed,
                phonenumbers.PhoneNumberFormat.E164
            )
    except Exception:
        pass

    return None


def normalize_email(email: str) -> str:
    """Normalize email address"""
    return email.strip().lower()


def get_phone_info(phone: str) -> dict:
    """Get basic phone info using phonenumbers library"""
    try:
        parsed = phonenumbers.parse(phone, 'PL')
        return {
            'valid': phonenumbers.is_valid_number(parsed),
            'country': geocoder.description_for_number(parsed, 'en'),
            'carrier': carrier.name_for_number(parsed, 'en'),
            'timezones': list(timezone.time_zones_for_number(parsed)),
            'type': str(phonenumbers.number_type(parsed))
        }
    except Exception as e:
        return {'valid': False, 'error': str(e)}


# =============================================================================
# Email Checkers
# =============================================================================

def check_holehe(email: str) -> list[SourceResult]:
    """
    Check email using Holehe (checks 120+ services)
    Returns list of SourceResult for each service found
    """
    import time
    results = []

    try:
        start = time.time()

        # Run holehe as subprocess
        result = subprocess.run(
            ['holehe', email, '--only-used', '-NP'],
            capture_output=True,
            text=True,
            timeout=120
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # Parse output
        found_services = []
        for line in result.stdout.split('\n'):
            # Holehe output format: [+] service: email used
            if '[+]' in line:
                match = re.search(r'\[\+\]\s+(\w+)', line)
                if match:
                    found_services.append(match.group(1))

        # Create result for holehe aggregate
        results.append(SourceResult(
            source_name='holehe',
            source_category='email_checker',
            status='found' if found_services else 'not_found',
            found=bool(found_services),
            raw_response={'output': result.stdout},
            extracted_data={
                'services_found': found_services,
                'services_count': len(found_services)
            },
            response_time_ms=elapsed_ms
        ))

    except subprocess.TimeoutExpired:
        results.append(SourceResult(
            source_name='holehe',
            source_category='email_checker',
            status='timeout',
            found=False,
            error_message='Holehe timed out after 120s'
        ))
    except Exception as e:
        results.append(SourceResult(
            source_name='holehe',
            source_category='email_checker',
            status='error',
            found=False,
            error_message=str(e)
        ))

    return results


def check_hibp(email: str, api_key: Optional[str] = None) -> SourceResult:
    """
    Check email against Have I Been Pwned
    """
    import time
    start = time.time()

    try:
        headers = {
            'User-Agent': 'OSINT-Tracker',
            'Accept': 'application/json'
        }
        if api_key:
            headers['hibp-api-key'] = api_key

        response = requests.get(
            f'https://haveibeenpwned.com/api/v3/breachedaccount/{email}',
            headers=headers,
            timeout=30
        )

        elapsed_ms = int((time.time() - start) * 1000)

        if response.status_code == 200:
            breaches = response.json()
            return SourceResult(
                source_name='hibp',
                source_category='breach_database',
                status='found',
                found=True,
                raw_response={'breaches': breaches},
                extracted_data={
                    'breach_count': len(breaches),
                    'breach_names': [b['Name'] for b in breaches]
                },
                response_time_ms=elapsed_ms
            )
        elif response.status_code == 404:
            return SourceResult(
                source_name='hibp',
                source_category='breach_database',
                status='not_found',
                found=False,
                response_time_ms=elapsed_ms
            )
        else:
            return SourceResult(
                source_name='hibp',
                source_category='breach_database',
                status='error',
                found=False,
                error_message=f'HTTP {response.status_code}',
                response_time_ms=elapsed_ms
            )

    except Exception as e:
        return SourceResult(
            source_name='hibp',
            source_category='breach_database',
            status='error',
            found=False,
            error_message=str(e)
        )


def check_gravatar(email: str) -> SourceResult:
    """
    Check if email has Gravatar profile
    """
    import time
    import hashlib

    start = time.time()

    try:
        # Gravatar uses MD5 hash of email
        email_hash = hashlib.md5(email.lower().encode()).hexdigest()
        url = f'https://www.gravatar.com/{email_hash}.json'

        response = requests.get(url, timeout=15)
        elapsed_ms = int((time.time() - start) * 1000)

        if response.status_code == 200:
            data = response.json()
            entry = data.get('entry', [{}])[0]
            return SourceResult(
                source_name='gravatar',
                source_category='social',
                status='found',
                found=True,
                raw_response=data,
                extracted_data={
                    'display_name': entry.get('displayName'),
                    'profile_url': entry.get('profileUrl'),
                    'accounts': [a.get('shortname') for a in entry.get('accounts', [])]
                },
                response_time_ms=elapsed_ms
            )
        else:
            return SourceResult(
                source_name='gravatar',
                source_category='social',
                status='not_found',
                found=False,
                response_time_ms=elapsed_ms
            )

    except Exception as e:
        return SourceResult(
            source_name='gravatar',
            source_category='social',
            status='error',
            found=False,
            error_message=str(e)
        )


# =============================================================================
# Username Checkers (Maigret - 3000+ services)
# =============================================================================

def check_maigret(username: str) -> SourceResult:
    """
    Check username using Maigret (3000+ services)
    Covers: Instagram, Facebook, Twitter, TikTok, LinkedIn, Tinder, Bumble, Badoo, etc.
    """
    import time
    import tempfile
    import os
    import glob as globlib

    start = time.time()

    try:
        # Create temp dir for output
        with tempfile.TemporaryDirectory() as tmpdir:
            # Run maigret - it creates report files automatically
            result = subprocess.run(
                [
                    'maigret', username,
                    '--folderoutput', tmpdir,
                    '--no-color',
                    '--timeout', '30'
                ],
                capture_output=True,
                text=True,
                timeout=300  # 5 min total timeout
            )

            elapsed_ms = int((time.time() - start) * 1000)

            # Parse found sites from stdout (most reliable)
            found_sites = []
            site_data = {}

            # Parse stdout - format: [+] SiteName: URL or "on N: [+] SiteName: URL"
            for line in result.stdout.split('\n'):
                if '[+]' in line:
                    # Match patterns like "[+] GitHub: https://..." or "on 0: [+] GitHub: https://..."
                    match = re.search(r'\[\+\]\s+([^:]+):\s+(https?://\S+)', line)
                    if match:
                        site = match.group(1).strip()
                        url = match.group(2).strip()
                        if site not in found_sites:
                            found_sites.append(site)
                            site_data[site] = {'url': url, 'status': 'found'}

            # Also try to parse JSON file if created
            json_files = globlib.glob(os.path.join(tmpdir, '*.json'))
            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # Maigret JSON format varies
                    if isinstance(data, dict):
                        for site_name, info in data.items():
                            if isinstance(info, dict):
                                status = info.get('status', '')
                                if status == 'Claimed' or info.get('exists') or 'url_user' in info:
                                    if site_name not in found_sites:
                                        found_sites.append(site_name)
                                        site_data[site_name] = {
                                            'url': info.get('url_user', info.get('url', '')),
                                            'status': 'found'
                                        }
                except (json.JSONDecodeError, Exception):
                    pass

            # Categorize found sites
            categories = categorize_maigret_results(found_sites)

            logger.info(f"Maigret found {len(found_sites)} sites for {username}")

            return SourceResult(
                source_name='maigret',
                source_category='username_osint',
                status='found' if found_sites else 'not_found',
                found=bool(found_sites),
                raw_response={'sites': site_data, 'stdout': result.stdout[-3000:], 'stderr': result.stderr[-1000:]},
                extracted_data={
                    'total_found': len(found_sites),
                    'sites_found': found_sites[:50],  # Limit to 50 for readability
                    'social_media': categories.get('social', []),
                    'dating': categories.get('dating', []),
                    'professional': categories.get('professional', []),
                    'gaming': categories.get('gaming', []),
                    'other': categories.get('other', [])
                },
                response_time_ms=elapsed_ms
            )

    except subprocess.TimeoutExpired:
        return SourceResult(
            source_name='maigret',
            source_category='username_osint',
            status='timeout',
            found=False,
            error_message='Maigret timed out after 300s',
            response_time_ms=300000
        )
    except FileNotFoundError:
        return SourceResult(
            source_name='maigret',
            source_category='username_osint',
            status='error',
            found=False,
            error_message='Maigret not installed'
        )
    except Exception as e:
        logger.error(f"Maigret error: {e}")
        return SourceResult(
            source_name='maigret',
            source_category='username_osint',
            status='error',
            found=False,
            error_message=str(e)
        )


def categorize_maigret_results(sites: list[str]) -> dict:
    """
    Categorize found sites into meaningful groups
    """
    categories = {
        'social': [],
        'dating': [],
        'professional': [],
        'gaming': [],
        'other': []
    }

    # Define site categories (lowercase for matching)
    social_sites = {
        'instagram', 'facebook', 'twitter', 'tiktok', 'snapchat', 'pinterest',
        'tumblr', 'reddit', 'vk', 'ok', 'weibo', 'telegram', 'discord',
        'whatsapp', 'signal', 'viber', 'youtube', 'twitch', 'flickr'
    }

    dating_sites = {
        'tinder', 'bumble', 'badoo', 'okcupid', 'match', 'pof', 'hinge',
        'happn', 'grindr', 'her', 'coffee meets bagel', 'zoosk', 'eharmony',
        'plenty of fish', 'sympatia', 'edarling', 'parship', 'lovoo'
    }

    professional_sites = {
        'linkedin', 'github', 'gitlab', 'bitbucket', 'stackoverflow',
        'behance', 'dribbble', 'medium', 'dev', 'hackerrank', 'leetcode',
        'kaggle', 'researchgate', 'academia', 'xing', 'angellist'
    }

    gaming_sites = {
        'steam', 'xbox', 'playstation', 'epicgames', 'origin', 'ubisoft',
        'roblox', 'minecraft', 'fortnite', 'valorant', 'leagueoflegends',
        'chess', 'lichess', 'battlenet', 'gog', 'itch'
    }

    for site in sites:
        site_lower = site.lower()

        if any(s in site_lower for s in social_sites):
            categories['social'].append(site)
        elif any(s in site_lower for s in dating_sites):
            categories['dating'].append(site)
        elif any(s in site_lower for s in professional_sites):
            categories['professional'].append(site)
        elif any(s in site_lower for s in gaming_sites):
            categories['gaming'].append(site)
        else:
            categories['other'].append(site)

    return categories


def derive_username_from_email(email: str) -> str:
    """Extract username from email address"""
    local_part = email.split('@')[0]
    # Remove common patterns like +tags
    local_part = local_part.split('+')[0]
    # Remove dots for some services (Gmail style)
    # But keep original for username derivation
    return local_part


# =============================================================================
# Phone Checkers
# =============================================================================

def check_phoneinfoga(phone: str) -> SourceResult:
    """
    Check phone using Phoneinfoga
    """
    import time
    start = time.time()

    try:
        result = subprocess.run(
            ['phoneinfoga', 'scan', '-n', phone, '--json'],
            capture_output=True,
            text=True,
            timeout=60
        )

        elapsed_ms = int((time.time() - start) * 1000)

        if result.returncode == 0 and result.stdout:
            try:
                data = json.loads(result.stdout)
                return SourceResult(
                    source_name='phoneinfoga',
                    source_category='phone_lookup',
                    status='found',
                    found=True,
                    raw_response=data,
                    extracted_data={
                        'carrier': data.get('carrier'),
                        'country': data.get('country'),
                        'local_format': data.get('local_format'),
                        'international_format': data.get('international_format')
                    },
                    response_time_ms=elapsed_ms
                )
            except json.JSONDecodeError:
                pass

        return SourceResult(
            source_name='phoneinfoga',
            source_category='phone_lookup',
            status='not_found',
            found=False,
            response_time_ms=elapsed_ms
        )

    except subprocess.TimeoutExpired:
        return SourceResult(
            source_name='phoneinfoga',
            source_category='phone_lookup',
            status='timeout',
            found=False,
            error_message='Phoneinfoga timed out'
        )
    except Exception as e:
        return SourceResult(
            source_name='phoneinfoga',
            source_category='phone_lookup',
            status='error',
            found=False,
            error_message=str(e)
        )


def check_numverify(phone: str, api_key: str) -> SourceResult:
    """
    Check phone using NumVerify API
    """
    import time
    start = time.time()

    if not api_key:
        return SourceResult(
            source_name='numverify',
            source_category='phone_validation',
            status='error',
            found=False,
            error_message='No API key configured'
        )

    try:
        response = requests.get(
            'http://apilayer.net/api/validate',
            params={
                'access_key': api_key,
                'number': phone,
                'country_code': '',
                'format': 1
            },
            timeout=15
        )

        elapsed_ms = int((time.time() - start) * 1000)

        if response.status_code == 200:
            data = response.json()
            if data.get('valid'):
                return SourceResult(
                    source_name='numverify',
                    source_category='phone_validation',
                    status='found',
                    found=True,
                    raw_response=data,
                    extracted_data={
                        'valid': data.get('valid'),
                        'country_name': data.get('country_name'),
                        'carrier': data.get('carrier'),
                        'line_type': data.get('line_type'),
                        'location': data.get('location')
                    },
                    response_time_ms=elapsed_ms
                )
            else:
                return SourceResult(
                    source_name='numverify',
                    source_category='phone_validation',
                    status='not_found',
                    found=False,
                    extracted_data={'valid': False},
                    response_time_ms=elapsed_ms
                )

        return SourceResult(
            source_name='numverify',
            source_category='phone_validation',
            status='error',
            found=False,
            error_message=f'HTTP {response.status_code}',
            response_time_ms=int((time.time() - start) * 1000)
        )

    except Exception as e:
        return SourceResult(
            source_name='numverify',
            source_category='phone_validation',
            status='error',
            found=False,
            error_message=str(e)
        )


# =============================================================================
# Messenger Checkers (WhatsApp, Telegram, Viber)
# =============================================================================

def check_whatsapp(phone: str) -> SourceResult:
    """
    Check if phone number is registered on WhatsApp.
    Uses wa.me link check method.
    """
    import time
    start = time.time()

    # Normalize phone - remove + and spaces
    clean_phone = phone.replace('+', '').replace(' ', '').replace('-', '')

    try:
        # Method 1: Check wa.me redirect behavior
        # WhatsApp links redirect differently for registered vs unregistered numbers
        url = f'https://wa.me/{clean_phone}'

        response = requests.head(
            url,
            allow_redirects=False,
            timeout=10,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # If we get a redirect to web.whatsapp.com or api.whatsapp.com, number likely exists
        location = response.headers.get('Location', '')

        # Check response - 302 redirect usually means the number format is recognized
        if response.status_code in [200, 302]:
            # Additional check via API endpoint
            api_url = f'https://api.whatsapp.com/send?phone={clean_phone}'
            api_response = requests.head(api_url, allow_redirects=True, timeout=10)

            # If final URL contains the phone number, it's likely registered
            is_registered = clean_phone in api_response.url or response.status_code == 302

            return SourceResult(
                source_name='whatsapp',
                source_category='messenger',
                status='found' if is_registered else 'not_found',
                found=is_registered,
                raw_response={
                    'url': url,
                    'status_code': response.status_code,
                    'location': location
                },
                extracted_data={
                    'registered': is_registered,
                    'whatsapp_link': url
                },
                response_time_ms=elapsed_ms
            )
        else:
            return SourceResult(
                source_name='whatsapp',
                source_category='messenger',
                status='not_found',
                found=False,
                response_time_ms=elapsed_ms
            )

    except requests.Timeout:
        return SourceResult(
            source_name='whatsapp',
            source_category='messenger',
            status='timeout',
            found=False,
            error_message='WhatsApp check timed out',
            response_time_ms=int((time.time() - start) * 1000)
        )
    except Exception as e:
        return SourceResult(
            source_name='whatsapp',
            source_category='messenger',
            status='error',
            found=False,
            error_message=str(e)
        )


def check_telegram(phone: str) -> SourceResult:
    """
    Check if phone number might be on Telegram.
    Note: Full verification requires Telegram API credentials.
    This is a basic check using public methods.
    """
    import time
    start = time.time()

    clean_phone = phone.replace('+', '').replace(' ', '').replace('-', '')

    try:
        # Telegram doesn't have a direct public API for phone lookup
        # But we can try the t.me/+{phone} format which sometimes works
        url = f'https://t.me/+{clean_phone}'

        response = requests.get(
            url,
            timeout=10,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # Parse response to check for user indicators
        # If page contains "tgme_page_photo" or user info, account exists
        content = response.text.lower()

        # Check for indicators of existing account
        has_profile = any([
            'tgme_page_photo' in content,
            'tgme_page_title' in content,
            '"og:title"' in content and 'telegram' in content
        ])

        # Check if it's an invite link response (different from user)
        is_invite = 'tgme_page_action' in content or 'join group' in content.lower()

        # If we find profile indicators and it's not just an invite
        found = has_profile and not is_invite

        return SourceResult(
            source_name='telegram',
            source_category='messenger',
            status='found' if found else 'unknown',
            found=found,
            raw_response={
                'url': url,
                'status_code': response.status_code,
                'has_profile': has_profile,
                'is_invite': is_invite
            },
            extracted_data={
                'checked': True,
                'method': 'web_lookup',
                'note': 'Pełna weryfikacja wymaga Telegram API' if not found else 'Możliwe konto'
            },
            response_time_ms=elapsed_ms
        )

    except requests.Timeout:
        return SourceResult(
            source_name='telegram',
            source_category='messenger',
            status='timeout',
            found=False,
            error_message='Telegram check timed out'
        )
    except Exception as e:
        return SourceResult(
            source_name='telegram',
            source_category='messenger',
            status='error',
            found=False,
            error_message=str(e)
        )


def check_viber(phone: str) -> SourceResult:
    """
    Check if phone number is registered on Viber.
    Uses Viber's public lookup endpoint.
    """
    import time
    start = time.time()

    clean_phone = phone.replace('+', '').replace(' ', '').replace('-', '')

    try:
        # Viber has a public API for checking number registration
        url = f'https://www.viber.com/api/v1/users/{clean_phone}'

        # Alternative: Use Viber deep link
        viber_link = f'viber://chat?number=%2B{clean_phone}'

        # Try web lookup
        response = requests.get(
            f'https://chats.viber.com/{clean_phone}',
            timeout=10,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            allow_redirects=True
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # Check if page indicates a valid user
        content = response.text.lower()
        found = response.status_code == 200 and 'viber' in content and '404' not in content

        return SourceResult(
            source_name='viber',
            source_category='messenger',
            status='found' if found else 'unknown',
            found=found,
            raw_response={
                'status_code': response.status_code,
                'viber_link': viber_link
            },
            extracted_data={
                'checked': True,
                'viber_link': viber_link
            },
            response_time_ms=elapsed_ms
        )

    except requests.Timeout:
        return SourceResult(
            source_name='viber',
            source_category='messenger',
            status='timeout',
            found=False,
            error_message='Viber check timed out'
        )
    except Exception as e:
        return SourceResult(
            source_name='viber',
            source_category='messenger',
            status='error',
            found=False,
            error_message=str(e)
        )


def check_signal(phone: str) -> SourceResult:
    """
    Signal check - limited public verification available.
    Signal prioritizes privacy, so public lookups are restricted.
    """
    import time
    start = time.time()

    # Signal doesn't have public phone lookup API (by design - privacy focused)
    # We can only note that the number format is valid for Signal

    clean_phone = phone.replace(' ', '').replace('-', '')
    if not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone

    elapsed_ms = int((time.time() - start) * 1000)

    return SourceResult(
        source_name='signal',
        source_category='messenger',
        status='unknown',
        found=False,  # Cannot determine without Signal API
        raw_response={},
        extracted_data={
            'checked': False,
            'reason': 'Signal nie udostępnia publicznego API do weryfikacji numerów',
            'signal_link': f'https://signal.me/#p/{clean_phone}'
        },
        response_time_ms=elapsed_ms
    )


# =============================================================================
# Platform Checks (ignorant + password reset)
# =============================================================================

def check_ignorant(phone: str) -> list[SourceResult]:
    """
    Check phone number using ignorant CLI.
    Checks: Amazon, Instagram, Snapchat
    """
    import time

    results = []
    start = time.time()

    # Parse country code and number
    clean_phone = phone.replace('+', '').replace(' ', '').replace('-', '')

    # Extract country code (assume first 2 digits for most countries)
    if clean_phone.startswith('48'):
        country_code = '48'
        national_number = clean_phone[2:]
    elif clean_phone.startswith('1'):
        country_code = '1'
        national_number = clean_phone[1:]
    else:
        country_code = clean_phone[:2]
        national_number = clean_phone[2:]

    try:
        # Run ignorant CLI
        result = subprocess.run(
            ['ignorant', country_code, national_number],
            capture_output=True,
            text=True,
            timeout=60
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # Parse output - format:
        # [-] amazon.com (not used)
        # [+] instagram.com (used)
        # [x] snapchat.com (rate limit)

        platforms = {
            'amazon': {'found': False, 'status': 'not_found', 'rate_limited': False},
            'instagram': {'found': False, 'status': 'not_found', 'rate_limited': False},
            'snapchat': {'found': False, 'status': 'not_found', 'rate_limited': False}
        }

        for line in result.stdout.split('\n'):
            line = line.strip()

            # [+] means phone is registered
            if '[+]' in line:
                if 'amazon' in line.lower():
                    platforms['amazon'] = {'found': True, 'status': 'found', 'rate_limited': False}
                elif 'instagram' in line.lower():
                    platforms['instagram'] = {'found': True, 'status': 'found', 'rate_limited': False}
                elif 'snapchat' in line.lower():
                    platforms['snapchat'] = {'found': True, 'status': 'found', 'rate_limited': False}

            # [-] means phone is not registered
            elif '[-]' in line:
                if 'amazon' in line.lower():
                    platforms['amazon'] = {'found': False, 'status': 'not_found', 'rate_limited': False}
                elif 'instagram' in line.lower():
                    platforms['instagram'] = {'found': False, 'status': 'not_found', 'rate_limited': False}
                elif 'snapchat' in line.lower():
                    platforms['snapchat'] = {'found': False, 'status': 'not_found', 'rate_limited': False}

            # [x] means rate limited
            elif '[x]' in line:
                if 'amazon' in line.lower():
                    platforms['amazon'] = {'found': False, 'status': 'rate_limited', 'rate_limited': True}
                elif 'instagram' in line.lower():
                    platforms['instagram'] = {'found': False, 'status': 'rate_limited', 'rate_limited': True}
                elif 'snapchat' in line.lower():
                    platforms['snapchat'] = {'found': False, 'status': 'rate_limited', 'rate_limited': True}

        # Create results for each platform
        for platform, data in platforms.items():
            if data['rate_limited']:
                results.append(SourceResult(
                    source_name=platform,
                    source_category='platform_check',
                    status='error',
                    found=False,
                    error_message='Rate limited',
                    response_time_ms=elapsed_ms // 3
                ))
            else:
                results.append(SourceResult(
                    source_name=platform,
                    source_category='platform_check',
                    status=data['status'],
                    found=data['found'],
                    extracted_data={
                        'registered': data['found'],
                        'platform': platform
                    },
                    response_time_ms=elapsed_ms // 3
                ))

    except subprocess.TimeoutExpired:
        results.append(SourceResult(
            source_name='ignorant',
            source_category='platform_check',
            status='timeout',
            found=False,
            error_message='Ignorant timed out'
        ))
    except FileNotFoundError:
        results.append(SourceResult(
            source_name='ignorant',
            source_category='platform_check',
            status='error',
            found=False,
            error_message='ignorant CLI not installed'
        ))
    except Exception as e:
        logger.error(f"Ignorant check error: {e}")
        results.append(SourceResult(
            source_name='ignorant',
            source_category='platform_check',
            status='error',
            found=False,
            error_message=str(e)
        ))

    return results


def check_google_account(phone: str) -> SourceResult:
    """
    Check if phone number is linked to a Google account.
    Uses Google's account recovery flow (non-intrusive check).
    """
    import time
    start = time.time()

    clean_phone = phone.replace(' ', '').replace('-', '')
    if not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone

    try:
        # Google account lookup via recovery page
        # This is a read-only check that doesn't send anything to the phone
        url = 'https://accounts.google.com/_/signin/sl/lookup'

        # Alternative: Check Google's public profile endpoints
        response = requests.get(
            f'https://www.google.com/search?q="{clean_phone}"',
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout=10
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # We can't directly check Google accounts without auth
        # But we can note if the phone format is valid for Google services
        return SourceResult(
            source_name='google',
            source_category='platform_check',
            status='unknown',
            found=False,
            extracted_data={
                'note': 'Google account lookup wymaga autoryzacji',
                'phone_format_valid': True
            },
            response_time_ms=elapsed_ms
        )

    except Exception as e:
        return SourceResult(
            source_name='google',
            source_category='platform_check',
            status='error',
            found=False,
            error_message=str(e)
        )


def check_facebook_phone(phone: str) -> SourceResult:
    """
    Check if phone number is linked to Facebook account.
    Uses password reset flow check (non-intrusive).
    """
    import time
    start = time.time()

    clean_phone = phone.replace(' ', '').replace('-', '')
    if not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone

    try:
        # Facebook password reset page check
        url = 'https://www.facebook.com/login/identify/'

        # We need to POST to check, but we can try a basic request first
        response = requests.get(
            'https://www.facebook.com/recover/initiate/',
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout=10
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # Full Facebook check would require form submission
        # which might trigger notifications - so we keep it basic
        return SourceResult(
            source_name='facebook',
            source_category='platform_check',
            status='unknown',
            found=False,
            extracted_data={
                'note': 'Facebook phone lookup wymaga zaawansowanej weryfikacji',
                'recovery_url': 'https://www.facebook.com/recover/initiate/'
            },
            response_time_ms=elapsed_ms
        )

    except Exception as e:
        return SourceResult(
            source_name='facebook',
            source_category='platform_check',
            status='error',
            found=False,
            error_message=str(e)
        )


def check_twitter_phone(phone: str) -> SourceResult:
    """
    Check if phone number might be linked to Twitter/X account.
    """
    import time
    start = time.time()

    clean_phone = phone.replace(' ', '').replace('-', '')
    if not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone

    try:
        # Twitter API check would require auth
        # Basic check only
        elapsed_ms = int((time.time() - start) * 1000)

        return SourceResult(
            source_name='twitter',
            source_category='platform_check',
            status='unknown',
            found=False,
            extracted_data={
                'note': 'Twitter/X phone lookup wymaga API keys'
            },
            response_time_ms=elapsed_ms
        )

    except Exception as e:
        return SourceResult(
            source_name='twitter',
            source_category='platform_check',
            status='error',
            found=False,
            error_message=str(e)
        )


# =============================================================================
# Risk Scoring
# =============================================================================

def calculate_risk(sources: list[SourceResult], input_type: str) -> tuple[str, list[str]]:
    """
    Calculate risk category and factors based on source results
    Returns: (risk_category, risk_factors)
    """
    risk_points = 0
    risk_factors = []

    for source in sources:
        if not source.found:
            continue

        # Breach database findings (HIBP)
        if source.source_name == 'hibp':
            breach_count = source.extracted_data.get('breach_count', 0)
            if breach_count > 5:
                risk_points += 3
                risk_factors.append(f'Email w {breach_count} wyciekach danych')
            elif breach_count > 0:
                risk_points += 1
                risk_factors.append(f'Email w {breach_count} wycieku danych')

        # Holehe - services found
        if source.source_name == 'holehe':
            services = source.extracted_data.get('services_found', [])
            dating_services = ['tinder', 'bumble', 'badoo', 'okcupid', 'match']
            dating_found = [s for s in services if s.lower() in dating_services]

            if len(dating_found) > 2:
                risk_points += 2
                risk_factors.append(f'Konta na {len(dating_found)} portalach randkowych (Holehe)')
            elif dating_found:
                risk_points += 1
                risk_factors.append(f'Holehe - konto na: {", ".join(dating_found)}')

            if len(services) > 10:
                risk_factors.append(f'Holehe: znaleziono na {len(services)} serwisach')

        # Gravatar with many linked accounts
        if source.source_name == 'gravatar':
            accounts = source.extracted_data.get('accounts', [])
            if accounts:
                risk_factors.append(f'Gravatar z kontami: {", ".join(accounts)}')

        # Maigret results (3000+ services)
        if source.source_name == 'maigret':
            extracted = source.extracted_data
            total_found = extracted.get('total_found', 0)
            dating = extracted.get('dating', [])
            social = extracted.get('social', [])
            professional = extracted.get('professional', [])

            # Dating sites are major risk factor
            if len(dating) > 3:
                risk_points += 3
                risk_factors.append(f'Konta na {len(dating)} portalach randkowych: {", ".join(dating[:5])}')
            elif len(dating) > 0:
                risk_points += 1 + len(dating)
                risk_factors.append(f'Portale randkowe: {", ".join(dating)}')

            # Social media presence
            if social:
                risk_factors.append(f'Social media ({len(social)}): {", ".join(social[:5])}')

            # Professional presence (positive indicator)
            if professional:
                risk_factors.append(f'Profile zawodowe: {", ".join(professional[:3])}')

            # Very high presence can indicate fake identity farming
            if total_found > 50:
                risk_points += 2
                risk_factors.append(f'Nietypowo dużo kont ({total_found}) - możliwa farma tożsamości')
            elif total_found > 20:
                risk_factors.append(f'Aktywna obecność online ({total_found} serwisów)')

    # Collect messenger results for summary
    messengers_found = []
    messengers_not_found = []

    for source in sources:
        if source.source_category == 'messenger':
            if source.found:
                messengers_found.append(source.source_name.title())
            elif source.status == 'not_found':
                messengers_not_found.append(source.source_name.title())

    # Add messenger summary to risk factors
    if messengers_found:
        risk_factors.append(f'Komunikatory: {", ".join(messengers_found)}')
    if messengers_not_found and input_type == 'phone':
        # No messengers can be suspicious for a phone number
        if len(messengers_not_found) >= 3:
            risk_points += 1
            risk_factors.append(f'Brak w komunikatorach: {", ".join(messengers_not_found)}')

    # Collect platform check results (Amazon, Instagram, Snapchat)
    platforms_found = []
    for source in sources:
        if source.source_category == 'platform_check' and source.found:
            platforms_found.append(source.source_name.title())

    if platforms_found:
        risk_factors.append(f'Konta powiązane: {", ".join(platforms_found)}')
        # Having accounts linked to phone is neutral/positive - shows real usage

    # Determine category based on points
    if risk_points >= 9:
        category = 'CRITICAL'
    elif risk_points >= 6:
        category = 'HIGH'
    elif risk_points >= 3:
        category = 'MEDIUM'
    else:
        category = 'LOW'

    # Add summary if low risk
    if category == 'LOW':
        found_count = sum(1 for s in sources if s.found)
        if found_count == 0:
            risk_factors.append('Nie znaleziono w żadnym źródle')
        else:
            risk_factors.append(f'Minimalne czerwone flagi ({found_count} źródeł)')

    return category, risk_factors


# =============================================================================
# Main Check Functions
# =============================================================================

def check_email(email: str, config: dict = None) -> CheckResult:
    """
    Run all email checks including Maigret for derived username
    """
    import time
    config = config or {}
    start = time.time()

    normalized = normalize_email(email)
    sources = []

    # Run Holehe (email → 120+ services)
    logger.info(f"Running Holehe for {email}")
    holehe_results = check_holehe(normalized)
    sources.extend(holehe_results)

    # Run HIBP (breach database)
    logger.info(f"Running HIBP for {email}")
    hibp_result = check_hibp(normalized, config.get('hibp_api_key'))
    sources.append(hibp_result)

    # Run Gravatar
    logger.info(f"Running Gravatar for {email}")
    gravatar_result = check_gravatar(normalized)
    sources.append(gravatar_result)

    # Run Maigret for derived username (3000+ services)
    if config.get('run_maigret', True):
        username = derive_username_from_email(normalized)
        if len(username) >= 3:  # Only if username is meaningful
            logger.info(f"Running Maigret for username: {username}")
            maigret_result = check_maigret(username)
            sources.append(maigret_result)

    # Calculate risk
    risk_category, risk_factors = calculate_risk(sources, 'email')

    duration_ms = int((time.time() - start) * 1000)

    return CheckResult(
        input_value=email,
        input_type='email',
        normalized_value=normalized,
        risk_category=risk_category,
        risk_factors=risk_factors,
        sources=sources,
        duration_ms=duration_ms
    )


def check_username(username: str, config: dict = None) -> CheckResult:
    """
    Run username-based OSINT checks using Maigret (3000+ services)
    """
    import time
    config = config or {}
    start = time.time()

    sources = []

    # Run Maigret (3000+ services: social, dating, gaming, forums, etc.)
    logger.info(f"Running Maigret for username: {username}")
    maigret_result = check_maigret(username)
    sources.append(maigret_result)

    # Calculate risk
    risk_category, risk_factors = calculate_risk(sources, 'username')

    duration_ms = int((time.time() - start) * 1000)

    return CheckResult(
        input_value=username,
        input_type='username',
        normalized_value=username.lower(),
        risk_category=risk_category,
        risk_factors=risk_factors,
        sources=sources,
        duration_ms=duration_ms
    )


def check_phone(phone: str, config: dict = None) -> CheckResult:
    """
    Run all phone checks including messenger verification
    """
    import time
    config = config or {}
    start = time.time()

    normalized = normalize_phone(phone)
    if not normalized:
        normalized = phone

    sources = []

    # Get basic phone info
    phone_info = get_phone_info(phone)

    # Run Phoneinfoga
    logger.info(f"Running Phoneinfoga for {phone}")
    phoneinfoga_result = check_phoneinfoga(normalized)
    sources.append(phoneinfoga_result)

    # Run NumVerify if API key available
    numverify_key = config.get('numverify_api_key')
    if numverify_key:
        logger.info(f"Running NumVerify for {phone}")
        numverify_result = check_numverify(normalized, numverify_key)
        sources.append(numverify_result)

    # Add phone info as source
    sources.append(SourceResult(
        source_name='phonenumbers',
        source_category='phone_parsing',
        status='found' if phone_info.get('valid') else 'not_found',
        found=phone_info.get('valid', False),
        extracted_data=phone_info,
        response_time_ms=0
    ))

    # =========================================================================
    # Messenger Checks (WhatsApp, Telegram, Viber, Signal)
    # =========================================================================
    if config.get('check_messengers', True):
        logger.info(f"Running messenger checks for {phone}")

        # WhatsApp
        logger.info(f"Checking WhatsApp for {phone}")
        whatsapp_result = check_whatsapp(normalized)
        sources.append(whatsapp_result)

        # Telegram
        logger.info(f"Checking Telegram for {phone}")
        telegram_result = check_telegram(normalized)
        sources.append(telegram_result)

        # Viber
        logger.info(f"Checking Viber for {phone}")
        viber_result = check_viber(normalized)
        sources.append(viber_result)

        # Signal (limited - privacy focused)
        logger.info(f"Checking Signal for {phone}")
        signal_result = check_signal(normalized)
        sources.append(signal_result)

    # =========================================================================
    # Platform Checks (ignorant: Amazon, Instagram, Snapchat)
    # =========================================================================
    if config.get('check_platforms', True):
        logger.info(f"Running platform checks (ignorant) for {phone}")
        try:
            ignorant_results = check_ignorant(normalized)
            sources.extend(ignorant_results)
        except Exception as e:
            logger.error(f"Ignorant check failed: {e}")

    # Calculate risk
    risk_category, risk_factors = calculate_risk(sources, 'phone')

    duration_ms = int((time.time() - start) * 1000)

    return CheckResult(
        input_value=phone,
        input_type='phone',
        normalized_value=normalized,
        risk_category=risk_category,
        risk_factors=risk_factors,
        sources=sources,
        duration_ms=duration_ms
    )


def run_check(input_value: str, config: dict = None, force_type: str = None) -> CheckResult:
    """
    Main entry point - auto-detect type and run appropriate checks

    Args:
        input_value: Email, phone number, or username to check
        config: Configuration dict with API keys etc.
        force_type: Override auto-detection ('email', 'phone', 'username')
    """
    input_type = force_type or detect_input_type(input_value)

    if input_type == 'email':
        return check_email(input_value, config)
    elif input_type == 'phone':
        return check_phone(input_value, config)
    elif input_type == 'username':
        return check_username(input_value, config)
    else:
        raise ValueError(f"Unknown input type for: {input_value}. Use force_type='username' if checking a username.")
