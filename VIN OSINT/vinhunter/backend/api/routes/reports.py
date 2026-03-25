from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Literal

from core.database import db
from core.report_generator import get_report_generator

router = APIRouter()


class ReportRequest(BaseModel):
    format: Literal["html_self", "html_images"] = "html_self"


@router.post("/reports/{scan_id}")
async def generate_report(scan_id: str, request: ReportRequest):
    scan = await db.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Skan nie znaleziony")

    gen = get_report_generator(db)
    file_path, file_size = await gen.generate_html_self_contained(scan_id)
    report_id = await db.save_report(scan_id, request.format, file_path, file_size)

    return {"report_id": report_id, "file_path": file_path, "file_size_bytes": file_size}


@router.get("/reports")
async def list_reports():
    return await db.list_reports()


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str):
    report = await db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Raport nie znaleziony")

    file_path = Path(report["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Plik raportu nie istnieje")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="text/html",
    )
