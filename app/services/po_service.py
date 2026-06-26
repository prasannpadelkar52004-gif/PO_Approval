"""
PO Service — business logic layer between API endpoints and the DB.
All database writes go through here, keeping endpoints thin.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    PurchaseOrder, POLineItem, ApprovalStep, AuditLog, ApprovalChain,
    POStatus, ApprovalAction, AuditAction, User, POPriority
)
from app.schemas.po import POCreate, POLineItemCreate, POApproveRequest
from app.services.approval_engine import ApprovalEngine, POStateMachine


# ── Fixed clause text per PO type ───────────────────────────────────────────
# Single source of truth for default Terms & Conditions text shown when a
# requester opens a New PO form. Editable by the requester before submit —
# this only pre-fills the textareas, it does not lock the fields.
# Fill in the real wording here when ready; empty string = no pre-fill.
PO_TYPE_CLAUSES = {
    "service": {
        "penalty_clauses":    "",
        "delivery_terms":     "",
        "warranty_terms":     "",
        "special_conditions": "",
    },
    "supply": {
        "penalty_clauses":    "",
        "delivery_terms":     "",
        "warranty_terms":     "",
        "special_conditions": "",
    },
    "technology": {
        "penalty_clauses":    "",
        "delivery_terms":     "",
        "warranty_terms":     "",
        "special_conditions": "",
    },
}


class POService:

    # ── PO Number Generation ──────────────────────────────────────────────────

    @staticmethod
    async def generate_po_number(session: AsyncSession) -> str:
        """Generates sequential PO numbers: PO-2026-0001"""
        year = datetime.utcnow().year
        result = await session.execute(
            select(func.count(PurchaseOrder.id)).where(
                func.extract("year", PurchaseOrder.created_at) == year
            )
        )
        count = result.scalar_one() + 1
        return f"PO-{year}-{count:04d}"

    # ── Create PO ─────────────────────────────────────────────────────────────

    @staticmethod
    async def create_po(
        session: AsyncSession,
        data: POCreate,
        requester: User,
        chains: list[ApprovalChain],
    ) -> PurchaseOrder:

        # Calculate totals from line items
        subtotal = Decimal(0)
        gst_total = Decimal(0)
        line_items = []

        for i, item_data in enumerate(data.line_items):
            amount    = item_data.quantity * item_data.unit_rate
            gst_amt   = amount * (item_data.gst_percent / 100)
            total     = amount + gst_amt
            subtotal  += amount
            gst_total += gst_amt

            line_items.append(POLineItem(
                sort_order=i,
                sub_category=getattr(item_data, 'sub_category', None),
                description=item_data.description,
                unit_of_measure=item_data.unit_of_measure,
                quantity=item_data.quantity,
                unit_rate=item_data.unit_rate,
                amount=amount,
                gst_percent=item_data.gst_percent,
                gst_amount=gst_amt,
                total=total,
            ))

        grand_total = subtotal + gst_total

        # Dynamic levels based on site approvers present + MD Owner as final
        required_levels = 2  # default: L1 + MD
        if getattr(data, 'site_id', None):
            from app.models.models import User as _User, UserRole as _UserRole
            from uuid import UUID as _UUID
            # Count distinct roles present for this site (in order)
            _ordered_roles = [
                _UserRole.L1_APPROVER,
                _UserRole.L2_APPROVER,
                _UserRole.L3_APPROVER,
                _UserRole.L4_APPROVER,
                _UserRole.FINANCE,
            ]
            _levels_with_approvers = 0
            for _role in _ordered_roles:
                _count = (await session.execute(
                    select(_User).where(
                        _User.site_id == _UUID(str(data.site_id)),
                        _User.is_active == True,
                        _User.role == _role,
                    )
                )).scalars().first()
                if _count:
                    _levels_with_approvers += 1
            # +1 for MD Owner as final level always
            required_levels = _levels_with_approvers + 1 if _levels_with_approvers else 2
        po_number = await POService.generate_po_number(session)

        # per-line-item sub_category budget check
        # Groups line items by sub_category and checks each group's total
        # against that sub_category's remaining budget.
        # If ANY sub_category is over budget, the whole PO is flagged.
        exceeds_budget = False
        budget_category_id = None
        if hasattr(data, 'site_id') and data.site_id:
            from app.models.models import BudgetCategory
            from sqlalchemy import select as _select, func as _func
            from uuid import UUID as _BUUID
            from collections import defaultdict

            # Group line item totals by sub_category
            _sub_totals = defaultdict(Decimal)
            for _item in data.line_items:
                _sub = getattr(_item, 'sub_category', None)
                _amt = _item.quantity * _item.unit_rate
                _amt_with_gst = _amt + (_amt * _item.gst_percent / 100)
                _sub_totals[_sub or '__none__'] += _amt_with_gst

            for _sub_key, _sub_total in _sub_totals.items():
                _sub_val = None if _sub_key == '__none__' else _sub_key
                if _sub_val:
                    # Check specific sub-category budget
                    _bq = _select(BudgetCategory).where(
                        BudgetCategory.site_id == _BUUID(str(data.site_id)),
                        BudgetCategory.category == data.po_category,
                        BudgetCategory.sub_category == _sub_val,
                        BudgetCategory.is_active == True,
                    )
                    _bc = (await session.execute(_bq)).scalars().first()
                    if _bc:
                        if budget_category_id is None:
                            budget_category_id = _bc.id
                        _remaining = _bc.budget_amount - _bc.spent_amount
                        if _sub_total > _remaining:
                            exceeds_budget = True
                else:
                    # No sub_category on line item — check category total
                    _agg_q = _select(
                        _func.sum(BudgetCategory.budget_amount).label('total_budget'),
                        _func.sum(BudgetCategory.spent_amount).label('total_spent'),
                    ).where(
                        BudgetCategory.site_id == _BUUID(str(data.site_id)),
                        BudgetCategory.category == data.po_category,
                        BudgetCategory.is_active == True,
                    )
                    _agg = (await session.execute(_agg_q)).first()
                    if _agg and _agg.total_budget:
                        _remaining = float(_agg.total_budget or 0) - float(_agg.total_spent or 0)
                        if float(_sub_total) > _remaining:
                            exceeds_budget = True
                            if budget_category_id is None:
                                _first_q = _select(BudgetCategory).where(
                                    BudgetCategory.site_id == _BUUID(str(data.site_id)),
                                    BudgetCategory.category == data.po_category,
                                    BudgetCategory.is_active == True,
                                ).limit(1)
                                _first = (await session.execute(_first_q)).scalars().first()
                                if _first:
                                    budget_category_id = _first.id

        from uuid import UUID as _UUID
        po = PurchaseOrder(
            po_number=po_number,
            requester_id=requester.id,
            department_id=data.department_id,
            project_id=data.project_id,
            vendor_id=data.vendor_id,
            po_category=data.po_category,
            sub_category=getattr(data, 'sub_category', None),
            site_id=_UUID(data.site_id) if getattr(data, 'site_id', None) else None,
            budget_category_id=budget_category_id,
            exceeds_budget=exceeds_budget,
            description=data.description,
            delivery_address=data.delivery_address,
            penalty_clauses=getattr(data, "penalty_clauses", None),
            delivery_terms=getattr(data, "delivery_terms", None),
            warranty_terms=getattr(data, "warranty_terms", None),
            special_conditions=getattr(data, "special_conditions", None),
            required_by=data.required_by,
            payment_terms=data.payment_terms,
            priority=data.priority,
            subtotal=subtotal,
            gst_amount=gst_total,
            total_amount=grand_total,
            required_levels=required_levels,
            status=POStatus.DRAFT,
        )

        session.add(po)
        await session.flush()  # get po.id

        for item in line_items:
            item.purchase_order_id = po.id
            session.add(item)

        # Audit log
        session.add(AuditLog(
            purchase_order_id=po.id,
            actor_id=requester.id,
            action=AuditAction.CREATED,
            from_status=None,
            to_status=POStatus.DRAFT,
        ))

        await session.commit()
        await session.refresh(po)

        # ── Notify MD if budget exceeded ──────────────────────────────────
        if po.exceeds_budget:
            try:
                # ── DIRECT EMAIL MODE (free tier — no worker needed) ───────
                from app.tasks.notifications import send_budget_exceed_email
                await send_budget_exceed_email(None, str(po.id))
                # ── END DIRECT EMAIL MODE ──────────────────────────────────

                # ══ ARQ WORKER MODE — uncomment below when worker is running ══
                # from arq import create_pool
                # from arq.connections import RedisSettings
                # from app.core.config import settings as _settings
                # _url = _settings.REDIS_URL.replace("redis://", "")
                # _host, _port = _url.split(":") if ":" in _url else (_url, "6379")
                # redis = await create_pool(RedisSettings(host=_host, port=int(_port)))
                # await redis.enqueue_job("send_budget_exceed_email", str(po.id))
                # await redis.aclose()
                # ══ END ARQ WORKER MODE ═══════════════════════════════════════
            except Exception as _e:
                import logging
                logging.getLogger(__name__).warning("Budget exceed email failed: %s", _e)

        return po

    # ── Submit PO ─────────────────────────────────────────────────────────────

    @staticmethod
    async def submit_po(
        session: AsyncSession,
        po: PurchaseOrder,
        requester: User,
    ) -> PurchaseOrder:
        if po.requester_id != requester.id:
            raise PermissionError("Only the requester can submit this PO")
        if po.status not in (POStatus.DRAFT, POStatus.RETURNED):
            raise ValueError(f"Cannot submit PO in status: {po.status}")
        if po.exceeds_budget and not getattr(po, "budget_authorized", False):
            raise PermissionError("Budget exceeded — waiting for MD authorization before submission")

        sm = POStateMachine(po)
        prev = po.status
        sm.submit()
        po.status = sm.current_state
        po.submitted_at = datetime.utcnow()
        po.current_level = 1

        session.add(AuditLog(
            purchase_order_id=po.id,
            actor_id=requester.id,
            action=AuditAction.SUBMITTED,
            from_status=prev,
            to_status=po.status,
        ))

        await session.commit()
        await session.refresh(po)

        # ── Trigger email notifications ─────────────────────────────────────
        try:
            # ── DIRECT EMAIL MODE (free tier — no worker needed) ───────────
            from app.tasks.notifications import send_approval_request_email
            await send_approval_request_email(None, str(po.id), 1)
            # ── END DIRECT EMAIL MODE ──────────────────────────────────────

            # ══ ARQ WORKER MODE — uncomment below when worker is running ══
            # from arq import create_pool
            # from arq.connections import RedisSettings
            # from app.core.config import settings as _settings
            # _url = _settings.REDIS_URL.replace("redis://", "")
            # _host, _port = _url.split(":") if ":" in _url else (_url, "6379")
            # redis = await create_pool(RedisSettings(host=_host, port=int(_port)))
            # await redis.enqueue_job("send_approval_request_email", str(po.id), 1)
            # await redis.aclose()
            # ══ END ARQ WORKER MODE ═══════════════════════════════════════
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning("Email notify failed: %s", _e)

        return po

    # ── Approve / Reject / Return PO ──────────────────────────────────────────

    @staticmethod
    async def process_approval(
        session: AsyncSession,
        po: PurchaseOrder,
        approver: User,
        req: POApproveRequest,
    ) -> PurchaseOrder:

        can, reason = ApprovalEngine.can_user_approve(approver, po)
        if not can:
            raise PermissionError(reason)

        prev_status = po.status
        current_level = ApprovalEngine.current_approval_level(po.status)
        sm = POStateMachine(po)

        if req.action == ApprovalAction.APPROVE:
            trigger = ApprovalEngine.get_next_trigger(po.status, po.required_levels)
            getattr(sm, trigger)()
            po.status = sm.current_state
            po.current_level = current_level + 1
            audit_action = AuditAction.APPROVED

            if po.status == POStatus.APPROVED:
                po.approved_at = datetime.utcnow()
                # Update budget spent amount
                if po.budget_category_id:
                    from app.models.models import BudgetCategory
                    budget_cat = await session.get(BudgetCategory, po.budget_category_id)
                    if budget_cat:
                        budget_cat.spent_amount += po.total_amount

        elif req.action == ApprovalAction.REJECT:
            if not req.comments:
                raise ValueError("Rejection reason (comments) is required")
            sm.reject()
            po.status = sm.current_state
            po.rejection_reason = req.comments
            po.rejected_at = datetime.utcnow()
            audit_action = AuditAction.REJECTED

        elif req.action == ApprovalAction.RETURN:
            if not req.comments:
                raise ValueError("Return reason (comments) is required")
            sm.return_po()
            po.status = sm.current_state
            po.return_reason = req.comments
            po.current_level = 0
            audit_action = AuditAction.RETURNED

        else:
            raise ValueError(f"Unknown action: {req.action}")

        # Record the approval step
        session.add(ApprovalEngine.build_approval_step(
            po, approver, current_level, req.action, req.comments
        ))

        # Audit log
        session.add(ApprovalEngine.build_audit_log(
            po, approver, audit_action, prev_status, po.status, req.comments
        ))

        await session.commit()
        await session.refresh(po)

        # ── Trigger email notifications ─────────────────────────────────────
        try:
            # ── DIRECT EMAIL MODE (free tier — no worker needed) ───────────
            from app.tasks.notifications import send_status_update_email, send_approval_request_email
            action_str = req.action.value.lower()
            await send_status_update_email(None, str(po.id), action_str, po.status.value)
            next_level = {"l1_approved": 2, "l2_approved": 3, "l3_approved": 4, "l4_approved": 5, "l5_approved": 6}.get(po.status.value)
            if next_level:
                await send_approval_request_email(None, str(po.id), next_level)
            # ── END DIRECT EMAIL MODE ──────────────────────────────────────

            # ══ ARQ WORKER MODE — uncomment below when worker is running ══
            # from arq import create_pool
            # from arq.connections import RedisSettings
            # from app.core.config import settings as _settings
            # _url = _settings.REDIS_URL.replace("redis://", "")
            # _host, _port = _url.split(":") if ":" in _url else (_url, "6379")
            # redis = await create_pool(RedisSettings(host=_host, port=int(_port)))
            # action_str = req.action.value.lower()
            # await redis.enqueue_job("send_status_update_email", str(po.id), action_str, po.status.value)
            # next_level = {"l1_approved": 2, "l2_approved": 3, "l3_approved": 4, "l4_approved": 5, "l5_approved": 6}.get(po.status.value)
            # if next_level:
            #     await redis.enqueue_job("send_approval_request_email", str(po.id), next_level)
            # await redis.aclose()
            # ══ END ARQ WORKER MODE ═══════════════════════════════════════
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning("Email notify failed: %s", _e)

        return po

    # ── Get PO with relations ─────────────────────────────────────────────────

    @staticmethod
    async def get_po_detail(
        session: AsyncSession,
        po_id: UUID,
    ) -> Optional[PurchaseOrder]:
        result = await session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == po_id)
            .options(
                selectinload(PurchaseOrder.requester),
                selectinload(PurchaseOrder.vendor),
                selectinload(PurchaseOrder.site),
                selectinload(PurchaseOrder.department),
                selectinload(PurchaseOrder.project),
                selectinload(PurchaseOrder.line_items),
                selectinload(PurchaseOrder.approval_steps).selectinload(ApprovalStep.approver),
                selectinload(PurchaseOrder.audit_logs).selectinload(AuditLog.actor),
                selectinload(PurchaseOrder.attachments),
            )
        )
        return result.scalar_one_or_none()

    # ── List POs ──────────────────────────────────────────────────────────────

    @staticmethod
    async def list_pos(
        session: AsyncSession,
        user: User,
        status: Optional[POStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PurchaseOrder]:
        from app.models.models import UserRole

        q = select(PurchaseOrder).options(
            selectinload(PurchaseOrder.requester),
            selectinload(PurchaseOrder.vendor),
        ).order_by(PurchaseOrder.created_at.desc()).limit(limit).offset(offset)

        # Requesters see only their own POs
        if user.role == UserRole.REQUESTER:
            q = q.where(PurchaseOrder.requester_id == user.id)

        if status:
            q = q.where(PurchaseOrder.status == status)

        result = await session.execute(q)
        return result.scalars().all()
