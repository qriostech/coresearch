"""Serves iteration visual files by absolute path."""
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/visuals/file")
def get_visual_file(path: str = Query(...)):
    if not os.path.isfile(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path)
