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

        # Check budget if site_id provided
        exceeds_budget = False
        budget_category_id = None
        if hasattr(data, 'site_id') and data.site_id:
            from app.models.models import BudgetCategory
            from sqlalchemy import select as _select, func as _func
            from uuid import UUID as _BUUID

            if hasattr(data, 'sub_category') and data.sub_category:
                # Specific sub-category budget check
                budget_q = _select(BudgetCategory).where(
                    BudgetCategory.site_id == _BUUID(str(data.site_id)),
                    BudgetCategory.category == data.po_category,
                    BudgetCategory.sub_category == data.sub_category,
                    BudgetCategory.is_active == True,
                )
                budget_result = await session.execute(budget_q)
                budget_cat = budget_result.scalars().first()
                if budget_cat:
                    budget_category_id = budget_cat.id
                    remaining = budget_cat.budget_amount - budget_cat.spent_amount
                    if grand_total > remaining:
                        exceeds_budget = True
            else:
                # No sub-category — check total budget for entire category
                agg_q = _select(
                    _func.sum(BudgetCategory.budget_amount).label("total_budget"),
                    _func.sum(BudgetCategory.spent_amount).label("total_spent"),
                ).where(
                    BudgetCategory.site_id == _BUUID(str(data.site_id)),
                    BudgetCategory.category == data.po_category,
                    BudgetCategory.is_active == True,
                )
                agg_result = await session.execute(agg_q)
                agg = agg_result.first()
                if agg and agg.total_budget:
                    total_budget = float(agg.total_budget or 0)
                    total_spent = float(agg.total_spent or 0)
                    remaining = total_budget - total_spent
                    if float(grand_total) > remaining:
                        exceeds_budget = True
                        # Use first active budget category for reference
                        first_cat_q = _select(BudgetCategory).where(
                            BudgetCategory.site_id == _BUUID(str(data.site_id)),
                            BudgetCategory.category == data.po_category,
                            BudgetCategory.is_active == True,
                        ).limit(1)
                        first_cat_result = await session.execute(first_cat_q)
                        first_cat = first_cat_result.scalars().first()
                        if first_cat:
                            budget_category_id = first_cat.id

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
                from arq import create_pool
                from arq.connections import RedisSettings
                from app.core.config import settings as _settings
                _url = _settings.REDIS_URL.replace("redis://", "")
                _host, _port = _url.split(":") if ":" in _url else (_url, "6379")
                redis = await create_pool(RedisSettings(host=_host, port=int(_port)))
                await redis.enqueue_job("send_budget_exceed_email", str(po.id))
                await redis.aclose()
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
            from arq import create_pool
            from arq.connections import RedisSettings
            from app.core.config import settings as _settings
            _url = _settings.REDIS_URL.replace("redis://", "")
            _host, _port = _url.split(":") if ":" in _url else (_url, "6379")
            redis = await create_pool(RedisSettings(host=_host, port=int(_port)))
            await redis.enqueue_job("send_approval_request_email", str(po.id), 1)
            await redis.aclose()
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
            from arq import create_pool
            from arq.connections import RedisSettings
            from app.core.config import settings as _settings
            _url = _settings.REDIS_URL.replace("redis://", "")
            _host, _port = _url.split(":") if ":" in _url else (_url, "6379")
            redis = await create_pool(RedisSettings(host=_host, port=int(_port)))
            action_str = req.action.value.lower()
            await redis.enqueue_job("send_status_update_email", str(po.id), action_str, po.status.value)
            next_level = {"l1_approved": 2, "l2_approved": 3, "l3_approved": 4, "l4_approved": 5, "l5_approved": 6}.get(po.status.value)
            if next_level:
                await redis.enqueue_job("send_approval_request_email", str(po.id), next_level)
            await redis.aclose()
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
