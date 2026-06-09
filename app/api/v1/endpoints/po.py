"""
PO API Endpoints
----------------
POST   /api/v1/pos/           → create draft PO
GET    /api/v1/pos/           → list POs (filtered by role)
GET    /api/v1/pos/{id}       → get PO detail
POST   /api/v1/pos/{id}/submit       → submit for approval
POST   /api/v1/pos/{id}/approve      → approve / reject / return
GET    /api/v1/pos/{id}/audit        → full audit trail
GET    /api/v1/dashboard/stats       → dashboard counts
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.models import (
    PurchaseOrder, ApprovalChain, POStatus, User
)
from app.schemas.po import (
    POCreate, PODetail, POSummary, POApproveRequest, POApproveResponse,
    DashboardStats, AuditLogRead, ApprovalStepRead
)
from app.services.po_service import POService
from app.api.v1.deps import get_current_active_user
from app.tasks.notifications import send_approval_request_email, send_status_update_email

router = APIRouter(prefix="/pos", tags=["Purchase Orders"])


async def _get_chains(session: AsyncSession) -> list[ApprovalChain]:
    result = await session.execute(
        select(ApprovalChain).where(ApprovalChain.is_active == True)
    )
    return result.scalars().all()


async def _get_po_or_404(po_id: UUID, session: AsyncSession) -> PurchaseOrder:
    po = await POService.get_po_detail(session, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=PODetail, status_code=status.HTTP_201_CREATED)
async def create_po(
    data: POCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    chains = await _get_chains(session)
    po = await POService.create_po(session, data, current_user, chains)
    return await POService.get_po_detail(session, po.id)


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[POSummary])
async def list_pos(
    status_filter: Optional[POStatus] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    pos = await POService.list_pos(
        session, current_user, status_filter, limit, offset
    )
    # Build summary with joined names
    summaries = []
    for po in pos:
        summaries.append(POSummary(
            id=po.id,
            po_number=po.po_number,
            status=po.status,
            priority=po.priority,
            po_category=po.po_category,
            total_amount=po.total_amount,
            required_by=po.required_by,
            created_at=po.created_at,
            requester_name=po.requester.full_name if po.requester else "—",
            vendor_name=po.vendor.name if po.vendor else "—",
        ))
    return summaries


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{po_id}", response_model=PODetail)
async def get_po(
    po_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    return await _get_po_or_404(po_id, session)


# ── Submit ────────────────────────────────────────────────────────────────────

@router.post("/{po_id}/submit", response_model=POApproveResponse)
async def submit_po(
    po_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    po = await _get_po_or_404(po_id, session)
    try:
        po = await POService.submit_po(session, po, current_user)
    except (PermissionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fire email notification in background
    background_tasks.add_task(
        send_approval_request_email, po_id=str(po.id), level=1
    )

    return POApproveResponse(
        po_number=po.po_number,
        new_status=po.status,
        message=f"PO {po.po_number} submitted for approval",
    )


# ── Approve / Reject / Return ─────────────────────────────────────────────────

@router.post("/{po_id}/approve", response_model=POApproveResponse)
async def process_approval(
    po_id: UUID,
    req: POApproveRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    po = await _get_po_or_404(po_id, session)
    try:
        po = await POService.process_approval(session, po, current_user, req)
    except (PermissionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Notify relevant parties
    background_tasks.add_task(
        send_status_update_email,
        po_id=str(po.id),
        action=req.action.value,
        new_status=po.status.value,
    )

    action_labels = {"approve": "approved", "reject": "rejected", "return": "returned"}
    label = action_labels.get(req.action.value, req.action.value)
    return POApproveResponse(
        po_number=po.po_number,
        new_status=po.status,
        message=f"PO {po.po_number} has been {label}",
    )


# ── Audit Trail ───────────────────────────────────────────────────────────────

@router.get("/{po_id}/audit", response_model=list[AuditLogRead])
async def get_audit_trail(
    po_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    po = await _get_po_or_404(po_id, session)
    return [
        AuditLogRead(
            id=log.id,
            action=log.action,
            actor_name=log.actor.full_name if log.actor else "System",
            from_status=log.from_status,
            to_status=log.to_status,
            comments=log.comments,
            created_at=log.created_at,
        )
        for log in sorted(po.audit_logs, key=lambda x: x.created_at)
    ]


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    from app.models.models import UserRole
    from sqlalchemy import func
    from datetime import datetime

    now = datetime.utcnow()

    # POs pending this user's action based on their role
    pending_statuses = {
        UserRole.L1_APPROVER: [POStatus.SUBMITTED],
        UserRole.L2_APPROVER: [POStatus.L1_APPROVED],
        UserRole.L3_APPROVER: [POStatus.L2_APPROVED],
        UserRole.L4_APPROVER: [POStatus.L3_APPROVED],
        UserRole.FINANCE:     [POStatus.APPROVED],
        UserRole.ADMIN:       [POStatus.SUBMITTED, POStatus.L1_APPROVED,
                               POStatus.L2_APPROVED, POStatus.L3_APPROVED],
    }.get(current_user.role, [])

    pending_q = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.status.in_(pending_statuses)
    )
    pending = (await session.execute(pending_q)).scalar_one()

    my_open_q = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.requester_id == current_user.id,
        PurchaseOrder.status.not_in([POStatus.APPROVED, POStatus.REJECTED,
                                     POStatus.CANCELLED, POStatus.CLOSED])
    )
    my_open = (await session.execute(my_open_q)).scalar_one()

    approved_q = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.status == POStatus.APPROVED,
        func.extract("month", PurchaseOrder.approved_at) == now.month,
        func.extract("year", PurchaseOrder.approved_at) == now.year,
    )
    approved = (await session.execute(approved_q)).scalar_one()

    rejected_q = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.status == POStatus.REJECTED,
        func.extract("month", PurchaseOrder.rejected_at) == now.month,
        func.extract("year", PurchaseOrder.rejected_at) == now.year,
    )
    rejected = (await session.execute(rejected_q)).scalar_one()

    value_q = select(func.sum(PurchaseOrder.total_amount)).where(
        PurchaseOrder.status.in_(pending_statuses)
    )
    total_value = (await session.execute(value_q)).scalar_one() or 0

    return DashboardStats(
        pending_my_action=pending,
        my_open_pos=my_open,
        approved_this_month=approved,
        rejected_this_month=rejected,
        total_value_pending=total_value,
    )
