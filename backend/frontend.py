"""Serves the static frontend (Phase 4) from ../frontend at / and /assets/*."""

from pathlib import Path

from flask import Blueprint, send_from_directory

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

bp = Blueprint("frontend", __name__)


@bp.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html", max_age=0)


@bp.get("/assets/<path:filename>")
def assets(filename: str):
    return send_from_directory(FRONTEND_DIR / "assets", filename, max_age=0)
