from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from plugins.registry import plugin_registry
from core.database import db

router = APIRouter()


class PluginUpdate(BaseModel):
    enabled: bool
    settings: Optional[dict] = {}


@router.get("/plugins")
async def list_plugins():
    plugins = plugin_registry.get_all()
    db_configs = {c["name"]: c for c in await db.get_plugin_configs()}

    return [
        {
            "name": p.name,
            "display_name": p.display_name,
            "category": p.category.value,
            "country": p.country,
            "enabled": p.enabled,
            "requires_captcha": p.requires_captcha,
            "total_queries": db_configs.get(p.name, {}).get("total_queries", 0),
            "total_errors": db_configs.get(p.name, {}).get("total_errors", 0),
            "last_used": db_configs.get(p.name, {}).get("last_used"),
        }
        for p in plugins
    ]


@router.put("/plugins/{name}")
async def update_plugin(name: str, update: PluginUpdate):
    plugin = plugin_registry.get(name)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' nie znaleziony")

    plugin_registry.set_enabled(name, update.enabled)
    await db.upsert_plugin_config(name, update.enabled, update.settings or {})

    return {"name": name, "enabled": update.enabled}
