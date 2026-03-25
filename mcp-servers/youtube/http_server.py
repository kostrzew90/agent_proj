#!/usr/bin/env python3
"""
YouTube HTTP API Server
REST wrapper for YouTube tools - integration with OpenWebUI.
"""

import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

from server import youtube_embed, youtube_search, youtube_list, ensure_tables_exist

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "youtube-mcp"})


@app.route('/openapi.json', methods=['GET'])
@app.route('/', methods=['GET'])
def openapi_spec():
    """OpenAPI 3.0 specification for OpenWebUI integration."""
    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "YouTube MCP API",
            "description": "API do indeksowania i wyszukiwania semantycznego w transkrypcjach YouTube",
            "version": "1.0.0"
        },
        "servers": [
            {"url": "http://youtube-mcp:8765", "description": "Docker internal"},
            {"url": "http://localhost:8765", "description": "Local"}
        ],
        "paths": {
            "/youtube/embed": {
                "post": {
                    "operationId": "youtube_embed",
                    "summary": "Indeksuj film YouTube",
                    "description": "Pobiera transkrypcję z YouTube, generuje embeddingi i zapisuje do bazy wektorowej do późniejszego wyszukiwania semantycznego.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["url"],
                                    "properties": {
                                        "url": {
                                            "type": "string",
                                            "description": "URL filmu YouTube (np. https://youtube.com/watch?v=...)"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Film zaindeksowany",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "video_id": {"type": "string"},
                                            "title": {"type": "string"},
                                            "channel": {"type": "string"},
                                            "upload_date": {"type": "string"},
                                            "chunks_count": {"type": "integer"},
                                            "subtitle_language": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/youtube/search": {
                "post": {
                    "operationId": "youtube_search",
                    "summary": "Wyszukaj w transkrypcjach",
                    "description": "Wyszukiwanie semantyczne w zaindeksowanych transkrypcjach YouTube. Zwraca fragmenty tekstu z timestampami i similarity score.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["query"],
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "Zapytanie w języku naturalnym (np. 'co mówił o inflacji')"
                                        },
                                        "year": {
                                            "type": "integer",
                                            "description": "Filtruj po roku publikacji (opcjonalne)"
                                        },
                                        "title_filter": {
                                            "type": "string",
                                            "description": "Filtruj po fragmencie tytułu (opcjonalne)"
                                        },
                                        "limit": {
                                            "type": "integer",
                                            "default": 8,
                                            "description": "Maksymalna liczba wyników"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Wyniki wyszukiwania",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "title": {"type": "string"},
                                                "channel": {"type": "string"},
                                                "date": {"type": "string"},
                                                "text": {"type": "string"},
                                                "timestamp": {"type": "string"},
                                                "similarity": {"type": "number"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/youtube/list": {
                "get": {
                    "operationId": "youtube_list",
                    "summary": "Lista zaindeksowanych filmów",
                    "description": "Wyświetla listę wszystkich zaindeksowanych filmów YouTube z metadanymi.",
                    "responses": {
                        "200": {
                            "description": "Lista filmów",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "video_id": {"type": "string"},
                                                "title": {"type": "string"},
                                                "channel": {"type": "string"},
                                                "date": {"type": "string"},
                                                "chunks": {"type": "integer"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    return jsonify(spec)


@app.route('/youtube/embed', methods=['POST'])
def api_embed():
    """
    Index a YouTube video.

    Request: {"url": "https://youtube.com/watch?v=..."}
    Response: {"video_id": "...", "title": "...", "channel": "...", ...}
    """
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({"error": "Missing 'url' parameter"}), 400

        logger.info(f"Embedding video: {data['url']}")
        result = youtube_embed(data['url'])
        logger.info(f"Embedded: {result['title']} ({result['chunks_count']} chunks)")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Embed error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/youtube/search', methods=['POST'])
def api_search():
    """
    Semantic search in indexed transcripts.

    Request: {"query": "...", "year": 2024, "title_filter": "...", "limit": 8}
    Response: [{"title": "...", "text": "...", "timestamp": "...", "similarity": ...}, ...]
    """
    try:
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({"error": "Missing 'query' parameter"}), 400

        logger.info(f"Search: {data['query']}")
        results = youtube_search(
            query=data['query'],
            year=data.get('year'),
            title_filter=data.get('title_filter'),
            limit=data.get('limit', 8)
        )
        logger.info(f"Found {len(results)} results")
        return jsonify(results)

    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/youtube/list', methods=['GET'])
def api_list():
    """
    List all indexed videos.

    Response: [{"video_id": "...", "title": "...", "channel": "...", ...}, ...]
    """
    try:
        videos = youtube_list()
        return jsonify(videos)

    except Exception as e:
        logger.error(f"List error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# OpenWebUI Function Definitions
# =============================================================================

OPENWEBUI_TOOLS = [
    {
        "name": "youtube_embed",
        "description": "Indeksuje film YouTube - pobiera transkrypcję, generuje embeddingi i zapisuje do bazy wektorowej. Użyj aby dodać nowy film do wyszukiwania semantycznego.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL filmu YouTube (np. https://youtube.com/watch?v=...)"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "youtube_search",
        "description": "Wyszukiwanie semantyczne w transkrypcjach YouTube. Zwraca fragmenty tekstu z timestampami i podobieństwem do zapytania.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Zapytanie w języku naturalnym"
                },
                "year": {
                    "type": "integer",
                    "description": "Filtruj po roku publikacji (opcjonalne)"
                },
                "title_filter": {
                    "type": "string",
                    "description": "Filtruj po fragmencie tytułu (opcjonalne)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maksymalna liczba wyników (domyślnie 8)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "youtube_list",
        "description": "Wyświetla listę wszystkich zaindeksowanych filmów YouTube z metadanymi.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]


@app.route('/openwebui/tools', methods=['GET'])
def openwebui_tools():
    """Return tool definitions for OpenWebUI."""
    return jsonify({"tools": OPENWEBUI_TOOLS})


@app.route('/openwebui/call', methods=['POST'])
def openwebui_call():
    """
    Universal endpoint for OpenWebUI function calls.

    Request: {"name": "youtube_search", "arguments": {"query": "..."}}
    """
    try:
        data = request.get_json()
        name = data.get('name')
        args = data.get('arguments', {})

        if name == 'youtube_embed':
            result = youtube_embed(args['url'])
        elif name == 'youtube_search':
            result = youtube_search(
                query=args['query'],
                year=args.get('year'),
                title_filter=args.get('title_filter'),
                limit=args.get('limit', 8)
            )
        elif name == 'youtube_list':
            result = youtube_list()
        else:
            return jsonify({"error": f"Unknown function: {name}"}), 400

        return jsonify({"result": result})

    except Exception as e:
        logger.error(f"OpenWebUI call error: {e}")
        return jsonify({"error": str(e)}), 500


def main():
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8765'))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'

    logger.info(f"Starting YouTube HTTP API on http://{host}:{port}")
    logger.info("Endpoints:")
    logger.info("  POST /youtube/embed   - Index a video")
    logger.info("  POST /youtube/search  - Semantic search")
    logger.info("  GET  /youtube/list    - List videos")
    logger.info("  GET  /openwebui/tools - Tool definitions")
    logger.info("  POST /openwebui/call  - Universal function call")

    # Ensure tables exist on startup
    try:
        ensure_tables_exist()
    except Exception as e:
        logger.warning(f"Could not ensure tables: {e}")

    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
