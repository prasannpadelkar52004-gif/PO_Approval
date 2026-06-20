from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator

from app.models.models import (
    POStatus, POPriority, ApprovalAction, UserRole, AuditAction, POType
)


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: UserRole = UserRole.REQUESTER
    department_id: Optional[UUID] = None
    phone: Optional[str] = None


class UserRead(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    department_id: Optional[UUID]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── PO Line Item ──────────────────────────────────────────────────────────────

class POLineItemCreate(BaseModel):
    description: str
    unit_of_measure: str = "nos"
    quantity: Decimal
    unit_rate: Decimal
    gst_percent: Decimal = Decimal("0")

    @field_validator("quantity", "unit_rate")
    @classmethod
    def must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Must be greater than zero")
        return v


class POLineItemRead(BaseModel):
    id: UUID
    sort_order: int
    description: str
    unit_of_measure: str
    quantity: Decimal
    unit_rate: Decimal
    amount: Decimal
    gst_percent: Decimal
    gst_amount: Decimal
    total: Decimal

    model_config = {"from_attributes": True}


# ── Purchase Order ────────────────────────────────────────────────────────────

class POCreate(BaseModel):
    vendor_id: UUID
    department_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    po_category: str = "material"
    po_type: Optional[POType] = None
    description: str
    delivery_address: str
    required_by: datetime
    payment_terms: Optional[str] = None
    priority: POPriority = POPriority.NORMAL
    site_id: Optional[str] = None
    sub_category: Optional[str] = None
    penalty_clauses: Optional[str] = None
    delivery_terms: Optional[str] = None
    warranty_terms: Optional[str] = None
    special_conditions: Optional[str] = None
    line_items: List[POLineItemCreate]

    @field_validator("line_items")
    @classmethod
    def must_have_items(cls, v):
        if not v:
            raise ValueError("At least one line item is required")
        return v


class POSummary(BaseModel):
    id: UUID
    po_number: str
    status: POStatus
    priority: POPriority
    po_category: str
    total_amount: Decimal
    required_by: datetime
    created_at: datetime
    requester_name: str
    vendor_name: str

    model_config = {"from_attributes": True}


class ApprovalStepRead(BaseModel):
    id: UUID
    level: int
    action: ApprovalAction
    approver_name: str
    comments: Optional[str]
    acted_at: datetime

    model_config = {"from_attributes": True}


class AuditLogRead(BaseModel):
    id: UUID
    action: AuditAction
    actor_name: str
    from_status: Optional[POStatus]
    to_status: Optional[POStatus]
    comments: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PODetail(BaseModel):
    id: UUID
    po_number: str
    status: POStatus
    priority: POPriority
    po_category: str
    description: str
    delivery_address: str
    required_by: datetime
    payment_terms: Optional[str]
    subtotal: Decimal
    gst_amount: Decimal
    total_amount: Decimal
    current_level: int
    required_levels: int
    rejection_reason: Optional[str]
    return_reason: Optional[str]
    submitted_at: Optional[datetime]
    approved_at: Optional[datetime]
    created_at: datetime

    requester: UserRead
    line_items: List[POLineItemRead]
    approval_steps: List[ApprovalStepRead]
    audit_logs: List[AuditLogRead]

    model_config = {"from_attributes": True}


# ── Approval actions ──────────────────────────────────────────────────────────

class POApproveRequest(BaseModel):
    action: ApprovalAction
    comments: Optional[str] = None


class POApproveResponse(BaseModel):
    po_number: str
    new_status: POStatus
    message: str


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    pending_my_action: int
    my_open_pos: int
    approved_this_month: int
    rejected_this_month: int
    total_value_pending: Decimal
