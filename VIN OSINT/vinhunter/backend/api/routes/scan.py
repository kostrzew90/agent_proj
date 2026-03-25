import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator
import re

from core.database import db
from core.vin_decoder import validate_vin
from core.scan_engine import ScanEngine
from plugins.registry import plugin_registry
from api.websocket import ws_manager

router = APIRouter()


class ScanRequest(BaseModel):
    vin: str
    plate: Optional[str] = None

    @field_validator("vin")
    @classmethod
    def validate(cls, v: str) -> str:
        v = v.upper().strip()
        valid, err = validate_vin(v)
        if not valid:
            raise ValueError(err)
        return v


@router.post("/scan")
async def start_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    scan_id = await db.create_scan(request.vin, request.plate)
    engine = ScanEngine(plugin_registry, db, ws_manager)
    background_tasks.add_task(engine.run_scan, scan_id, request.vin, request.plate)
    return {"scan_id": scan_id, "vin": request.vin, "status": "running"}


@router.get("/scan/{scan_id}")
async def get_scan(scan_id: str):
    scan = await db.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Skan nie znaleziony")
    return scan


@router.get("/scan/{scan_id}/results")
async def get_scan_results(scan_id: str):
    scan = await db.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Skan nie znaleziony")
    results = await db.get_scan_results(scan_id)
    photos = await db.get_photos(scan_id)
    return {"scan": scan, "results": results, "photos": photos}


@router.delete("/scan/{scan_id}")
async def delete_scan(scan_id: str):
    scan = await db.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Skan nie znaleziony")
    await db.delete_scan(scan_id)
    return {"deleted": scan_id}


@router.get("/scans")
async def list_scans():
    return await db.list_scans()
