"""
/api/auth/* — Register, Login, Me
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

from app import db
from app.models.user import User

auth_bp = Blueprint("auth", __name__)


def _parse_register(data: dict):
    """Return (email, password, name, error_tuple) — error_tuple is None on success."""
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "")
    name     = (data.get("name")     or "").strip()

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return None, None, None, ("البريد الإلكتروني غير صالح", 422)
    if len(password) < 8:
        return None, None, None, ("كلمة المرور يجب أن تكون 8 أحرف على الأقل", 422)

    return email, password, name or None, None


@auth_bp.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    email, password, name, err = _parse_register(data)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "البريد الإلكتروني مستخدم بالفعل"}), 409

    user = User(email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": user.to_dict()}), 201


@auth_bp.post("/api/auth/login")
def login():
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "")

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "البريد الإلكتروني أو كلمة المرور غير صحيحة"}), 401

    if not user.is_active:
        return jsonify({"error": "الحساب معطل، تواصل مع الدعم"}), 403

    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": user.to_dict()}), 200


@auth_bp.get("/api/auth/me")
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    return jsonify(user.to_dict()), 200
