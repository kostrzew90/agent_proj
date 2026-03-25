from fastapi import APIRouter, HTTPException
from core.vin_decoder import validate_vin, decode_vin_basic
from plugins.registry import plugin_registry
from plugins.base import SourceCategory

router = APIRouter()


@router.get("/vin/validate/{vin}")
async def validate(vin: str):
    valid, error = validate_vin(vin.upper().strip())
    basic = decode_vin_basic(vin.upper().strip()) if valid else None
    return {"vin": vin.upper(), "valid": valid, "error": error, "basic_info": basic}


@router.get("/vin/decode/{vin}")
async def decode_vin(vin: str):
    """Tylko dekodowanie VIN przez wszystkie dostępne pluginy VIN_DECODE."""
    vin = vin.upper().strip()
    valid, error = validate_vin(vin)
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    decode_plugins = plugin_registry.get_by_category(SourceCategory.VIN_DECODE)
    if not decode_plugins:
        return {"vin": vin, "data": decode_vin_basic(vin), "source": "basic_offline"}

    import asyncio
    results = await asyncio.gather(
        *[p.search_by_vin(vin) for p in decode_plugins],
        return_exceptions=True
    )

    combined = decode_vin_basic(vin)
    for r in results:
        if isinstance(r, Exception):
            continue
        if r.status.value == "done":
            for k, v in r.data.items():
                if k not in combined and v:
                    combined[k] = v

    return {"vin": vin, "data": combined}
