"""
/api/payments/* — PRO subscription plans, subscribe, history
Admin approval is handled via /api/admin/payments/*
"""
import uuid
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.models.user import User
from app.models.payment import Payment, PLANS, PLAN_FEATURES, PAYMENT_ACCOUNTS, PAYMENT_METHODS

payments_bp = Blueprint("payments", __name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB base64 limit


@payments_bp.get("/api/payments/plans")
def get_plans():
    """Public — available subscription plans + payment account numbers."""
    plans = [{**plan, "features": PLAN_FEATURES} for plan in PLANS.values()]
    return jsonify({
        "plans":    plans,
        "features": PLAN_FEATURES,
        "accounts": PAYMENT_ACCOUNTS,
        "methods":  list(PAYMENT_METHODS),
    })


@payments_bp.post("/api/payments/subscribe")
@jwt_required()
def subscribe():
    """Create a pending payment record with receipt image."""
    user_id = int(get_jwt_identity())
    user    = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "المستخدم غير موجود"}), 404

    if user.is_pro:
        return jsonify({"error": "أنت مشترك بالفعل في الخطة المدفوعة"}), 409

    data           = request.get_json(silent=True) or {}
    plan_id        = (data.get("plan") or "").strip()
    payment_method = (data.get("payment_method") or "").strip()
    receipt_image  = data.get("receipt_image")   # base64 data-url string

    if plan_id not in PLANS:
        return jsonify({"error": "خطة غير صالحة"}), 422
    if payment_method not in PAYMENT_METHODS:
        return jsonify({"error": "طريقة دفع غير صالحة"}), 422
    if not receipt_image:
        return jsonify({"error": "يرجى إرفاق صورة إيصال الدفع"}), 422
    if len(receipt_image.encode()) > MAX_IMAGE_BYTES:
        return jsonify({"error": "حجم الصورة أكبر من 5 ميجا"}), 422

    plan = PLANS[plan_id]
    ref  = f"EGX-{uuid.uuid4().hex[:12].upper()}"

    payment = Payment(
        user_id        = user_id,
        plan           = plan_id,
        amount         = plan["price"],
        currency       = plan["currency"],
        status         = "pending",
        provider_ref   = ref,
        payment_method = payment_method,
        receipt_image  = receipt_image,
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "payment":      payment.to_dict(),
        "provider_ref": ref,
        "message":      "تم استلام طلبك بنجاح — في انتظار موافقة الادمن",
    }), 201


@payments_bp.get("/api/payments/history")
@jwt_required()
def payment_history():
    """List the authenticated user's payment records (latest first)."""
    user_id  = int(get_jwt_identity())
    payments = (
        Payment.query
        .filter_by(user_id=user_id)
        .order_by(Payment.created_at.desc())
        .all()
    )
    return jsonify({
        "total": len(payments),
        "items": [p.to_dict() for p in payments],
    })
