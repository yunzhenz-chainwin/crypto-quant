from fastapi import APIRouter
from backend.services.reader import available_symbols, last_updated

router = APIRouter()


@router.get("/symbols")
def get_symbols():
    return available_symbols()


@router.get("/status")
def get_status():
    return {"last_updated": last_updated()}
