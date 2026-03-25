#!/usr/bin/env python3
"""
OSINT Tracker HTTP API Server
REST API for OpenWebUI integration
"""

import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

from checkers import run_check, detect_input_type, check_username, CheckResult
from database import Database
from formatter import format_result_markdown

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Database instance
db = Database()

# Configuration from environment
CONFIG = {
    'numverify_api_key': os.getenv('NUMVERIFY_API_KEY'),
    'abstractapi_key': os.getenv('ABSTRACTAPI_KEY'),
    'hibp_api_key': os.getenv('HIBP_API_KEY'),
    'hunter_api_key': os.getenv('HUNTER_API_KEY')
}


# =============================================================================
# OpenAPI Specification
# =============================================================================

@app.route('/', methods=['GET'])
@app.route('/openapi.json', methods=['GET'])
def openapi_spec():
    """OpenAPI 3.1 specification for OpenWebUI"""
    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "OSINT Tracker API",
            "description": "API do weryfikacji numerów telefonów i adresów email przy użyciu narzędzi OSINT",
            "version": "1.0.0"
        },
        "servers": [
            {"url": "http://osint-tracker:8766", "description": "Docker internal"},
            {"url": "http://localhost:8766", "description": "Local"}
        ],
        "paths": {
            "/osint/check": {
                "post": {
                    "operationId": "osint_check",
                    "summary": "Sprawdź numer telefonu lub email",
                    "description": "Automatycznie wykrywa typ (telefon/email) i uruchamia odpowiednie sprawdzenia OSINT. Zwraca kategorię ryzyka i szczegóły ze wszystkich źródeł.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["input"],
                                    "properties": {
                                        "input": {
                                            "type": "string",
                                            "description": "Numer telefonu (np. +48123456789) lub adres email (np. test@example.com)"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Wynik sprawdzenia",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "input": {"type": "string"},
                                            "type": {"type": "string"},
                                            "risk_category": {"type": "string"},
                                            "risk_factors": {"type": "array", "items": {"type": "string"}},
                                            "sources_checked": {"type": "integer"},
                                            "sources_found": {"type": "integer"},
                                            "duration_ms": {"type": "integer"},
                                            "markdown": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/osint/history": {
                "post": {
                    "operationId": "osint_history",
                    "summary": "Historia sprawdzeń",
                    "description": "Pobiera historię poprzednich sprawdzeń dla danego numeru/email.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["input"],
                                    "properties": {
                                        "input": {
                                            "type": "string",
                                            "description": "Numer telefonu lub email do sprawdzenia historii"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Historia sprawdzeń"
                        }
                    }
                }
            },
            "/osint/check/username": {
                "post": {
                    "operationId": "osint_check_username",
                    "summary": "Sprawdź username na 3000+ serwisach",
                    "description": "Używa Maigret do sprawdzenia nazwy użytkownika na ponad 3000 serwisów: social media, portale randkowe, gaming, fora, etc.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["username"],
                                    "properties": {
                                        "username": {
                                            "type": "string",
                                            "description": "Nazwa użytkownika do sprawdzenia (np. john_doe)"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Wynik sprawdzenia username",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "username": {"type": "string"},
                                            "risk_category": {"type": "string"},
                                            "total_found": {"type": "integer"},
                                            "social_media": {"type": "array", "items": {"type": "string"}},
                                            "dating": {"type": "array", "items": {"type": "string"}},
                                            "professional": {"type": "array", "items": {"type": "string"}},
                                            "markdown": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/osint/list": {
                "get": {
                    "operationId": "osint_list",
                    "summary": "Lista wszystkich sprawdzeń",
                    "description": "Zwraca listę wszystkich wykonanych sprawdzeń posortowaną od najnowszych.",
                    "responses": {
                        "200": {
                            "description": "Lista sprawdzeń"
                        }
                    }
                }
            }
        }
    }
    return jsonify(spec)


# =============================================================================
# API Endpoints
# =============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "osint-tracker"})


@app.route('/osint/check', methods=['POST'])
def api_check():
    """
    Main OSINT check endpoint
    Auto-detects input type (phone/email) and runs appropriate checks
    """
    try:
        data = request.get_json()
        if not data or 'input' not in data:
            return jsonify({"error": "Missing 'input' parameter"}), 400

        input_value = data['input'].strip()
        input_type = detect_input_type(input_value)

        if input_type == 'unknown':
            return jsonify({
                "error": f"Cannot detect input type for: {input_value}. Please provide a valid phone number or email."
            }), 400

        logger.info(f"Running OSINT check for {input_type}: {input_value}")

        # Run the check
        result = run_check(input_value, CONFIG)

        # Save to database
        check_id = db.save_check(result)

        # Format response
        response = {
            'id': check_id,
            'input': result.input_value,
            'type': result.input_type,
            'normalized': result.normalized_value,
            'risk_category': result.risk_category,
            'risk_factors': result.risk_factors,
            'sources_checked': result.sources_checked,
            'sources_found': result.sources_found,
            'duration_ms': result.duration_ms,
            'timestamp': result.timestamp.isoformat(),
            'markdown': format_result_markdown(result)
        }

        logger.info(f"Check complete: {result.risk_category} ({result.sources_found}/{result.sources_checked} sources)")

        return jsonify(response)

    except Exception as e:
        logger.error(f"Check error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/osint/check/username', methods=['POST'])
def api_check_username():
    """
    Username OSINT check using Maigret (3000+ services)
    """
    try:
        data = request.get_json()
        if not data or 'username' not in data:
            return jsonify({"error": "Missing 'username' parameter"}), 400

        username = data['username'].strip()

        # Validate username
        if len(username) < 3 or len(username) > 30:
            return jsonify({"error": "Username must be 3-30 characters"}), 400

        logger.info(f"Running Maigret OSINT for username: {username}")

        # Run the check
        result = check_username(username, CONFIG)

        # Save to database
        check_id = db.save_check(result)

        # Extract Maigret-specific data
        maigret_data = {}
        for source in result.sources:
            if source.source_name == 'maigret':
                maigret_data = source.extracted_data
                break

        # Format response
        response = {
            'id': check_id,
            'username': result.input_value,
            'type': 'username',
            'risk_category': result.risk_category,
            'risk_factors': result.risk_factors,
            'total_found': maigret_data.get('total_found', 0),
            'social_media': maigret_data.get('social_media', []),
            'dating': maigret_data.get('dating', []),
            'professional': maigret_data.get('professional', []),
            'gaming': maigret_data.get('gaming', []),
            'sites_found': maigret_data.get('sites_found', [])[:20],  # Top 20
            'duration_ms': result.duration_ms,
            'timestamp': result.timestamp.isoformat(),
            'markdown': format_result_markdown(result)
        }

        logger.info(f"Username check complete: {maigret_data.get('total_found', 0)} sites found")

        return jsonify(response)

    except Exception as e:
        logger.error(f"Username check error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/osint/history', methods=['POST'])
def api_history():
    """
    Get check history for a specific input
    """
    try:
        data = request.get_json()
        if not data or 'input' not in data:
            return jsonify({"error": "Missing 'input' parameter"}), 400

        input_value = data['input'].strip()
        history = db.get_history(input_value)

        if not history:
            return jsonify({
                "message": f"Brak historii sprawdzeń dla: {input_value}",
                "history": []
            })

        # Format for response
        formatted = []
        for check in history:
            formatted.append({
                'id': check['id'],
                'timestamp': check['check_timestamp'].isoformat() if check['check_timestamp'] else None,
                'risk_category': check['risk_category'],
                'sources_checked': check['sources_checked'],
                'sources_found': check['sources_success']
            })

        return jsonify({
            "input": input_value,
            "checks_count": len(history),
            "history": formatted
        })

    except Exception as e:
        logger.error(f"History error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/osint/list', methods=['GET'])
def api_list():
    """
    List all checks
    """
    try:
        checks = db.get_all_checks(limit=50)

        formatted = []
        for check in checks:
            formatted.append({
                'id': check['id'],
                'input': check['input_value'],
                'type': check['input_type'],
                'timestamp': check['check_timestamp'].isoformat() if check['check_timestamp'] else None,
                'risk_category': check['risk_category'],
                'sources_found': check['sources_success']
            })

        return jsonify({
            "total": len(formatted),
            "checks": formatted
        })

    except Exception as e:
        logger.error(f"List error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/osint/details/<int:check_id>', methods=['GET'])
def api_details(check_id: int):
    """
    Get full details for a specific check
    """
    try:
        details = db.get_check_details(check_id)

        if not details:
            return jsonify({"error": f"Check {check_id} not found"}), 404

        return jsonify(details)

    except Exception as e:
        logger.error(f"Details error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Main
# =============================================================================

def main():
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8766'))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'

    logger.info(f"Starting OSINT Tracker on http://{host}:{port}")
    logger.info("Endpoints:")
    logger.info("  POST /osint/check    - Run OSINT check")
    logger.info("  POST /osint/history  - Get check history")
    logger.info("  GET  /osint/list     - List all checks")
    logger.info("  GET  /openapi.json   - OpenAPI spec")

    # Ensure database tables exist
    try:
        db.ensure_tables()
    except Exception as e:
        logger.warning(f"Could not ensure tables: {e}")

    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
