"""
/api/payments/* — PRO subscription plans, subscribe, history, confirm
"""
import uuid
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.models.user import User
from app.models.payment import Payment, PLANS, PLAN_FEATURES

payments_bp = Blueprint("payments", __name__)


@payments_bp.get("/api/payments/plans")
def get_plans():
    """Public — available subscription plans."""
    plans = [
        {**plan, "features": PLAN_FEATURES}
        for plan in PLANS.values()
    ]
    return jsonify({"plans": plans, "features": PLAN_FEATURES})


@payments_bp.post("/api/payments/subscribe")
@jwt_required()
def subscribe():
    """Create a pending payment record for the requested plan."""
    user_id = int(get_jwt_identity())
    user    = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "المستخدم غير موجود"}), 404

    if user.is_pro:
        return jsonify({"error": "أنت مشترك بالفعل في الخطة المدفوعة"}), 409

    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan", "").strip()
    if plan_id not in PLANS:
        return jsonify({"error": "خطة غير صالحة — اختر pro_monthly أو pro_annual"}), 422

    plan = PLANS[plan_id]
    ref  = f"EGX-{uuid.uuid4().hex[:12].upper()}"

    payment = Payment(
        user_id      = user_id,
        plan         = plan_id,
        amount       = plan["price"],
        currency     = plan["currency"],
        status       = "pending",
        provider_ref = ref,
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "payment":      payment.to_dict(),
        "provider_ref": ref,
        "instructions": "أرسل المبلغ عبر InstaPay إلى 01XXXXXXXXXX مع ذكر رقم المرجع",
    }), 201


@payments_bp.get("/api/payments/history")
@jwt_required()
def payment_history():
    """List the authenticated user's payment records (latest first)."""
    user_id = int(get_jwt_identity())
    payments = (
        Payment.query
        .filter_by(user_id=user_id)
        .order_by(Payment.created_at.desc())
        .all()
    )
    return jsonify({
        "total":  len(payments),
        "items":  [p.to_dict() for p in payments],
    })


@payments_bp.patch("/api/payments/<int:payment_id>/confirm")
@jwt_required()
def confirm_payment(payment_id: int):
    """Mark a pending payment as completed and activate PRO for the user."""
    user_id = int(get_jwt_identity())
    payment = db.session.get(Payment, payment_id)

    if not payment:
        return jsonify({"error": "الدفعة غير موجودة"}), 404
    if payment.user_id != user_id:
        return jsonify({"error": "غير مصرح"}), 403
    if payment.status != "pending":
        return jsonify({"error": f"لا يمكن تأكيد دفعة بحالة: {payment.status}"}), 422

    payment.status = "completed"
    user = db.session.get(User, user_id)
    if user:
        user.is_pro = True
    db.session.commit()

    return jsonify({
        "payment": payment.to_dict(),
        "is_pro":  True,
    })
