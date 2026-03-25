#!/usr/bin/env python3
"""
Output formatter for OSINT Tracker
Generates structured Markdown for OpenWebUI display
"""

from typing import Optional
from checkers import CheckResult, SourceResult


def get_risk_emoji(category: str) -> str:
    """Get emoji for risk category"""
    return {
        'LOW': '🟢',
        'MEDIUM': '🟡',
        'HIGH': '🟠',
        'CRITICAL': '🔴'
    }.get(category, '⚪')


def get_status_emoji(found: bool, status: str) -> str:
    """Get emoji for source status"""
    if status == 'error':
        return '⚠️'
    elif status == 'timeout':
        return '⏱️'
    elif found:
        return '✅'
    else:
        return '❌'


def format_result_markdown(result: CheckResult) -> str:
    """
    Format check result as structured Markdown for OpenWebUI
    """
    lines = []

    # Header
    risk_emoji = get_risk_emoji(result.risk_category)
    lines.append(f"## 🔍 Wynik sprawdzenia: {result.input_value}")
    lines.append("")
    lines.append(f"**Typ:** {result.input_type.upper()}")
    if result.normalized_value != result.input_value:
        lines.append(f"**Znormalizowany:** {result.normalized_value}")
    lines.append(f"**Kategoria ryzyka:** {risk_emoji} **{result.risk_category}**")
    lines.append("")

    # Risk factors
    if result.risk_factors:
        lines.append("### ⚠️ Czynniki ryzyka")
        for factor in result.risk_factors:
            lines.append(f"- {factor}")
        lines.append("")

    # Group sources by category
    categories = {}
    for source in result.sources:
        cat = source.source_category or 'other'
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(source)

    # Format each category
    category_names = {
        'email_checker': '📧 Serwisy (email)',
        'breach_database': '🔓 Wycieki danych',
        'social': '💬 Social Media',
        'phone_lookup': '📱 Informacje o numerze',
        'phone_validation': '✓ Walidacja numeru',
        'phone_parsing': '📋 Parsowanie numeru',
        'messenger': '📲 Komunikatory (WhatsApp, Telegram, Viber)',
        'platform_check': '🌐 Platformy (Amazon, Instagram, Snapchat)',
        'dating': '💕 Portale randkowe',
        'username_osint': '🔎 Username OSINT (Maigret)',
        'other': '📊 Inne źródła'
    }

    for cat, sources in categories.items():
        cat_name = category_names.get(cat, cat.title())
        lines.append(f"### {cat_name}")
        lines.append("")
        lines.append("| Źródło | Status | Szczegóły |")
        lines.append("|--------|--------|-----------|")

        for source in sources:
            emoji = get_status_emoji(source.found, source.status)
            status_text = "Znaleziono" if source.found else "Nie znaleziono"
            if source.status == 'error':
                status_text = f"Błąd: {source.error_message or 'unknown'}"
            elif source.status == 'timeout':
                status_text = "Timeout"

            # Extract key details
            details = format_source_details(source)

            lines.append(f"| {source.source_name} | {emoji} {status_text} | {details} |")

        lines.append("")

    # Statistics
    lines.append("### 📊 Statystyki")
    lines.append("")
    lines.append(f"- **Sprawdzono źródeł:** {result.sources_checked}")
    lines.append(f"- **Znaleziono w:** {result.sources_found}")
    lines.append(f"- **Czas sprawdzenia:** {result.duration_ms / 1000:.1f}s")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Sprawdzono: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC*")

    return "\n".join(lines)


def format_source_details(source: SourceResult) -> str:
    """Extract and format key details from source result"""
    details = []
    data = source.extracted_data

    if not data:
        return "-"

    # Holehe specific
    if source.source_name == 'holehe':
        services = data.get('services_found', [])
        if services:
            if len(services) > 5:
                details.append(f"{len(services)} serwisów: {', '.join(services[:5])}...")
            else:
                details.append(f"{', '.join(services)}")

    # HIBP specific
    elif source.source_name == 'hibp':
        breaches = data.get('breach_names', [])
        count = data.get('breach_count', 0)
        if count > 0:
            if count > 3:
                details.append(f"{count} wycieków: {', '.join(breaches[:3])}...")
            else:
                details.append(f"{', '.join(breaches)}")

    # Gravatar specific
    elif source.source_name == 'gravatar':
        name = data.get('display_name')
        accounts = data.get('accounts', [])
        if name:
            details.append(f"Nazwa: {name}")
        if accounts:
            details.append(f"Konta: {', '.join(accounts)}")

    # Phone info
    elif source.source_name == 'phonenumbers':
        country = data.get('country')
        carrier = data.get('carrier')
        if country:
            details.append(f"Kraj: {country}")
        if carrier:
            details.append(f"Operator: {carrier}")

    # NumVerify
    elif source.source_name == 'numverify':
        country = data.get('country_name')
        carrier = data.get('carrier')
        line_type = data.get('line_type')
        if country:
            details.append(f"Kraj: {country}")
        if carrier:
            details.append(f"Operator: {carrier}")
        if line_type:
            details.append(f"Typ: {line_type}")

    # Phoneinfoga
    elif source.source_name == 'phoneinfoga':
        carrier = data.get('carrier')
        country = data.get('country')
        if carrier:
            details.append(f"Operator: {carrier}")
        if country:
            details.append(f"Kraj: {country}")

    # Maigret (3000+ services)
    elif source.source_name == 'maigret':
        total = data.get('total_found', 0)
        social = data.get('social_media', [])
        dating = data.get('dating', [])
        professional = data.get('professional', [])

        if total > 0:
            details.append(f"**{total} serwisów**")

        if dating:
            details.append(f"💕 Randki: {', '.join(dating[:5])}")
        if social:
            social_preview = social[:5] if len(social) <= 5 else social[:4] + [f"+{len(social)-4}"]
            details.append(f"Social: {', '.join(social_preview)}")
        if professional:
            details.append(f"Praca: {', '.join(professional[:3])}")

    # Messenger checks (WhatsApp, Telegram, Viber, Signal)
    elif source.source_name == 'whatsapp':
        if source.found:
            link = data.get('whatsapp_link', '')
            details.append(f"Zarejestrowany")
            if link:
                details.append(f"[Link]({link})")
        else:
            details.append("Nie znaleziono")

    elif source.source_name == 'telegram':
        note = data.get('note', '')
        if source.found:
            details.append("Możliwe konto")
        elif note:
            details.append(note)
        else:
            details.append("Brak danych")

    elif source.source_name == 'viber':
        if source.found:
            details.append("Zarejestrowany")
        else:
            link = data.get('viber_link', '')
            details.append("Brak danych")

    elif source.source_name == 'signal':
        reason = data.get('reason', '')
        link = data.get('signal_link', '')
        if reason:
            details.append(reason)
        else:
            details.append("Brak publicznego API")

    # Platform checks (ignorant: Amazon, Instagram, Snapchat)
    elif source.source_name in ['amazon', 'instagram', 'snapchat']:
        if source.found:
            details.append("✅ Konto powiązane z numerem")
        else:
            details.append("Brak konta")

    elif source.source_name in ['google', 'facebook', 'twitter']:
        note = data.get('note', '')
        if note:
            details.append(note)
        else:
            details.append("Wymaga zaawansowanej weryfikacji")

    if not details:
        return "-"

    return "; ".join(details)


def format_history_markdown(history: list[dict], input_value: str) -> str:
    """Format check history as Markdown"""
    lines = []

    lines.append(f"## 📜 Historia sprawdzeń: {input_value}")
    lines.append("")

    if not history:
        lines.append("*Brak wcześniejszych sprawdzeń*")
        return "\n".join(lines)

    lines.append(f"**Liczba sprawdzeń:** {len(history)}")
    lines.append("")

    lines.append("| Data | Ryzyko | Źródła |")
    lines.append("|------|--------|--------|")

    for check in history:
        timestamp = check.get('timestamp', 'N/A')
        risk = check.get('risk_category', 'N/A')
        sources = f"{check.get('sources_found', 0)}/{check.get('sources_checked', 0)}"
        emoji = get_risk_emoji(risk)

        lines.append(f"| {timestamp} | {emoji} {risk} | {sources} |")

    return "\n".join(lines)
