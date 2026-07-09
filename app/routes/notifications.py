"""
/api/notifications — Notification inbox CRUD
User-id scoped (optional JWT — null user_id for anonymous sessions).
"""
from flask import Blueprint, jsonify, request, abort
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app import db
from app.models.notification import Notification, NOTIFICATION_TYPES
from app.utils.pro_guard import require_pro

notifications_bp = Blueprint("notifications", __name__)


def _get_user_id():
    """Return int user_id from JWT if present, else None."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity else None
    except Exception:
        return None


# ── GET /api/notifications ────────────────────────────────────────────────────

@notifications_bp.get("/api/notifications")
def list_notifications():
    err = require_pro()
    if err:
        return err
    user_id  = _get_user_id()
    unread_only = request.args.get("unread") == "1"
    limit       = min(int(request.args.get("limit", 50)), 100)
    offset      = int(request.args.get("offset", 0))

    q = Notification.query.filter_by(user_id=user_id)
    if unread_only:
        q = q.filter_by(is_read=False)
    q = q.order_by(Notification.created_at.desc())

    total   = q.count()
    unread  = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    items   = q.limit(limit).offset(offset).all()

    return jsonify({
        "total":  total,
        "unread": unread,
        "limit":  limit,
        "offset": offset,
        "items":  [n.to_dict() for n in items],
    })


# ── PATCH /api/notifications/<id>/read ────────────────────────────────────────

@notifications_bp.patch("/api/notifications/<int:notif_id>/read")
def mark_read(notif_id: int):
    user_id = _get_user_id()
    n = db.session.get(Notification, notif_id)
    if not n or n.user_id != user_id:
        abort(404)

    n.is_read = True
    db.session.commit()
    return jsonify(n.to_dict())


# ── PATCH /api/notifications/read-all ─────────────────────────────────────────

@notifications_bp.patch("/api/notifications/read-all")
def mark_all_read():
    user_id = _get_user_id()
    Notification.query.filter_by(user_id=user_id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})


# ── DELETE /api/notifications/<id> ────────────────────────────────────────────

@notifications_bp.delete("/api/notifications/<int:notif_id>")
def delete_notification(notif_id: int):
    user_id = _get_user_id()
    n = db.session.get(Notification, notif_id)
    if not n or n.user_id != user_id:
        abort(404)

    db.session.delete(n)
    db.session.commit()
    return "", 204


# ── DELETE /api/notifications (bulk clear all read) ───────────────────────────

@notifications_bp.delete("/api/notifications")
def clear_read():
    user_id = _get_user_id()
    Notification.query.filter_by(user_id=user_id, is_read=True).delete()
    db.session.commit()
    return jsonify({"ok": True})
