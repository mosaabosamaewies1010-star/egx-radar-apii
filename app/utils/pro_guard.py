"""
pro_guard.py — helpers for Free vs PRO access control.

Usage:
    from app.utils.pro_guard import current_is_pro, require_pro

    # Check silently (returns bool)
    if current_is_pro():
        ...

    # Hard gate — returns 403 JSON if not PRO
    err = require_pro()
    if err:
        return err
"""
from flask import jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request


def _get_user():
    """Return the current User model or None if unauthenticated."""
    try:
        verify_jwt_in_request(optional=True)
        uid = get_jwt_identity()
        if uid is None:
            return None
        from app.models.user import User
        return User.query.get(int(uid))
    except Exception:
        return None


def current_is_pro() -> bool:
    """True if the request carries a valid PRO JWT."""
    user = _get_user()
    return bool(user and user.is_pro)


def require_pro():
    """
    Return a 403 JSON response if not PRO, else None.

    Usage:
        err = require_pro()
        if err: return err
    """
    if not current_is_pro():
        return jsonify({
            "error": "هذه الميزة متاحة لمشتركي PRO فقط",
            "upgrade_url": "/payments",
            "pro_required": True,
        }), 403
    return None


# Free-tier limits
FREE_MAX_OPPORTUNITIES = 3
FREE_MAX_WATCHLIST     = 5
