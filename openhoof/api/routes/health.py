"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    from ..dependencies import get_manager
    
    try:
        manager = get_manager()
        inference_ok = await manager.inference.health_check()
    except Exception:
        inference_ok = False
    
    return {
        "status": "healthy",
        "components": {
            "api": True,
            "inference": inference_ok,
        }
    }


@router.get("/version")
async def version():
    """Get version info."""
    from openhoof import __version__
    return {"version": __version__}
