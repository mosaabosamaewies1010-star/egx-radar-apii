from flask import Blueprint, jsonify
from datetime import datetime, timezone

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health_check():
    return jsonify({
        "status": "ok",
        "service": "EGX Radar API",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
