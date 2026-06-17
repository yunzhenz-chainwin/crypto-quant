from fastapi import APIRouter
from backend.services.reader import load_correlation

router = APIRouter()


@router.get("/correlation")
def get_correlation():
    return load_correlation()
