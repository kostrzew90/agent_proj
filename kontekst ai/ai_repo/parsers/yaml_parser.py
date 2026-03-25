"""YAML parser — extracts services from docker-compose, config keys."""

from __future__ import annotations

import logging
import re

import yaml

from ai_repo.parsers.python_parser import EdgeInfo, ParseResult, SymbolInfo

logger = logging.getLogger(__name__)


def parse_yaml(file_path: str, source: str) -> ParseResult:
    """Parse YAML files (docker-compose, config.yaml, etc.)."""
    result = ParseResult()

    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as e:
        logger.warning(f"YAML parse error in {file_path}: {e}")
        return result

    if not isinstance(data, dict):
        return result

    # Docker-compose detection
    if "services" in data and isinstance(data["services"], dict):
        for svc_name, svc_config in data["services"].items():
            line = _find_line(source, svc_name)
            result.symbols.append(SymbolInfo(
                name=svc_name,
                kind="service",
                file_path=file_path,
                start_line=line,
                end_line=line,
                signature=svc_config.get("image", ""),
                docstring="",
            ))
            # depends_on edges
            deps = svc_config.get("depends_on", [])
            if isinstance(deps, dict):
                deps = list(deps.keys())
            for dep in deps:
                result.edges.append(EdgeInfo(
                    src_name=svc_name, src_kind="service",
                    dst_name=dep, dst_kind="service",
                    edge_type="depends_on",
                ))
            # volumes, ports as config refs
            for port in svc_config.get("ports", []):
                result.symbols.append(SymbolInfo(
                    name=f"{svc_name}:{port}",
                    kind="endpoint",
                    file_path=file_path,
                    start_line=line,
                    end_line=line,
                ))
    else:
        # Generic config — extract top-level keys
        for key in data.keys():
            line = _find_line(source, str(key))
            result.symbols.append(SymbolInfo(
                name=str(key),
                kind="config_key",
                file_path=file_path,
                start_line=line,
                end_line=line,
            ))

    return result


def _find_line(source: str, token: str) -> int:
    """Find the line number where a token first appears."""
    for i, line in enumerate(source.splitlines(), start=1):
        if token in line:
            return i
    return 1
