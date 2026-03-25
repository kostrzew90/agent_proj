import base64
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import structlog
from jinja2 import Environment, FileSystemLoader

from core.config import settings
from core.database import Database

logger = structlog.get_logger()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class ReportGenerator:
    def __init__(self, db: Database):
        self.db = db
        self.jinja = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )

    async def generate_html_self_contained(self, scan_id: str) -> tuple[str, int]:
        """Generuj self-contained HTML raport. Zwraca (file_path, file_size)."""
        scan = await self.db.get_scan(scan_id)
        results = await self.db.get_scan_results(scan_id)
        photos = await self.db.get_photos(scan_id)

        # Grupuj wyniki po kategorii
        grouped = {}
        for r in results:
            cat = r["category"]
            grouped.setdefault(cat, []).append(r)

        template = self.jinja.get_template("report_full.html")
        html = template.render(
            scan=scan,
            grouped_results=grouped,
            photos=photos,
            generated_at=datetime.utcnow().isoformat(),
            total=len(results),
            done=sum(1 for r in results if r["status"] == "done"),
            errors=sum(1 for r in results if r["status"] == "error"),
            no_data=sum(1 for r in results if r["status"] == "no_data"),
        )

        output_dir = Path(settings.reports_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        vin = scan["vin"]
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_path = output_dir / f"report_{vin}_{ts}.html"
        file_path.write_text(html, encoding="utf-8")

        size = file_path.stat().st_size
        logger.info("report.generated", scan_id=scan_id, path=str(file_path), size=size)
        return str(file_path), size


report_generator: Optional[ReportGenerator] = None


def get_report_generator(db: Database) -> ReportGenerator:
    global report_generator
    if report_generator is None:
        report_generator = ReportGenerator(db)
    return report_generator
