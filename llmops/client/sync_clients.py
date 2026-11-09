"""Kopiuje kanonicznego klienta do wszystkich projektow.

Uruchom z katalogu llmops/:  python client/sync_clients.py [--check]
--check zwraca kod 1, gdy ktoras kopia sie rozjechala (do CI).
"""
import hashlib
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).parent / "llmops_client.py"

TARGETS = [
    Path("../../RAG/backend/core/llmops_client.py"),
    Path("../../argus/argus/llmops_client.py"),
    Path("../../mcp-servers/llm-proxy/llmops_client.py"),
    Path("../../Selfmadeagent/orchestrator/agent/llmops_client.py"),
    Path("../../kontekst ai/ai_repo/core/llmops_client.py"),
    Path("../../trading-app/core/llmops_client.py"),
]


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    check = "--check" in sys.argv
    src_hash = digest(SRC)
    drift = []
    for t in TARGETS:
        t = (Path(__file__).parent / t).resolve()
        if check:
            if not t.exists() or digest(t) != src_hash:
                drift.append(str(t))
        else:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SRC, t)
            print(f"synced -> {t}")
    if check and drift:
        print("ROZJECHANE KOPIE:\n  " + "\n  ".join(drift))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
