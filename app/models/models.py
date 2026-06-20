"""
Database models for the PO Approval System.
All models use SQLModel — compatible with both SQLAlchemy and Pydantic.
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel, Column
from sqlalchemy import Text, Numeric, JSON


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    REQUESTER   = "REQUESTER"
    L1_APPROVER = "L1_APPROVER"
    L2_APPROVER = "L2_APPROVER"
    L3_APPROVER = "L3_APPROVER"
    L4_APPROVER = "L4_APPROVER"
    FINANCE     = "FINANCE"
    ADMIN       = "ADMIN"
    MD_OWNER    = "MD_OWNER"


class POStatus(str, Enum):
    DRAFT       = "draft"
    SUBMITTED   = "submitted"
    L1_APPROVED = "l1_approved"
    L2_APPROVED = "l2_approved"
    L3_APPROVED = "l3_approved"
    L4_APPROVED = "l4_approved"
    L5_APPROVED = "l5_approved"
    APPROVED    = "approved"
    REJECTED    = "rejected"
    RETURNED    = "returned"
    CANCELLED   = "cancelled"
    CLOSED      = "closed"


class POPriority(str, Enum):
    NORMAL  = "normal"
    URGENT  = "urgent"


class POType(str, Enum):
    SERVICE     = "service"
    SUPPLY      = "supply"
    TECHNOLOGY  = "technology"


class ApprovalAction(str, Enum):
    APPROVE  = "approve"
    REJECT   = "reject"
    RETURN   = "return"
    DELEGATE = "delegate"


class AuditAction(str, Enum):
    CREATED   = "created"
    UPDATED   = "updated"
    SUBMITTED = "submitted"
    APPROVED  = "approved"
    REJECTED  = "rejected"
    RETURNED  = "returned"
    CANCELLED = "cancelled"
    CLOSED    = "closed"
    DELEGATED = "delegated"
    COMMENT   = "comment"


# ── Base ──────────────────────────────────────────────────────────────────────

class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


# ── Department ────────────────────────────────────────────────────────────────

class Department(TimestampMixin, table=True):
    __tablename__ = "departments"

    id:          UUID = Field(default_factory=uuid4, primary_key=True)
    name:        str  = Field(max_length=120, index=True)
    code:        str  = Field(max_length=20, unique=True)
    is_active:   bool = Field(default=True)

    users:           List["User"]          = Relationship(back_populates="department")
    purchase_orders: List["PurchaseOrder"] = Relationship(back_populates="department")


# ── Project / Site ────────────────────────────────────────────────────────────

class Project(TimestampMixin, table=True):
    __tablename__ = "projects"

    id:          UUID = Field(default_factory=uuid4, primary_key=True)
    name:        str  = Field(max_length=200, index=True)
    code:        str  = Field(max_length=30, unique=True)
    cost_centre: str  = Field(max_length=30)
    is_active:   bool = Field(default=True)

    purchase_orders: List["PurchaseOrder"] = Relationship(back_populates="project")




# ── Site / Plant ──────────────────────────────────────────────────────────────

class Site(TimestampMixin, table=True):
    __tablename__ = "sites"

    id:           UUID           = Field(default_factory=uuid4, primary_key=True)
    name:         str            = Field(max_length=200, index=True)
    code:         str            = Field(max_length=20, unique=True)
    location:     Optional[str]  = Field(default=None, max_length=200)
    is_active:    bool           = Field(default=True)

    users:            List["User"]           = Relationship(back_populates="site")
    purchase_orders:  List["PurchaseOrder"]  = Relationship(back_populates="site")
    budget_categories:List["BudgetCategory"] = Relationship(back_populates="site")


# ── Budget Category ───────────────────────────────────────────────────────────

class BudgetCategory(TimestampMixin, table=True):
    __tablename__ = "budget_categories"

    id:               UUID           = Field(default_factory=uuid4, primary_key=True)
    site_id:          UUID           = Field(foreign_key="sites.id")
    project_id:       Optional[UUID] = Field(default=None, foreign_key="projects.id")
    category:         str            = Field(max_length=100)
    sub_category:     Optional[str]  = Field(default=None, max_length=100)
    budget_amount:    Decimal        = Field(sa_column=Column(Numeric(15, 2)))
    spent_amount:     Decimal        = Field(sa_column=Column(Numeric(15, 2)), default=0)
    is_active:        bool           = Field(default=True)

    site:    "Site"             = Relationship(back_populates="budget_categories")
    project: Optional["Project"] = Relationship()

# ── Vendor ────────────────────────────────────────────────────────────────────

class Vendor(TimestampMixin, table=True):
    __tablename__ = "vendors"

    id:          UUID           = Field(default_factory=uuid4, primary_key=True)
    name:        str            = Field(max_length=200, index=True)
    gst_number:  Optional[str]  = Field(default=None, max_length=20)
    email:       Optional[str]  = Field(default=None, max_length=200)
    phone:       Optional[str]  = Field(default=None, max_length=20)
    address:     Optional[str]  = Field(default=None, sa_column=Column(Text))
    is_active:   bool           = Field(default=True)

    purchase_orders: List["PurchaseOrder"] = Relationship(back_populates="vendor")


# ── User ──────────────────────────────────────────────────────────────────────

class User(TimestampMixin, table=True):
    __tablename__ = "users"

    id:               UUID          = Field(default_factory=uuid4, primary_key=True)
    email:            str           = Field(max_length=200, unique=True, index=True)
    full_name:        str           = Field(max_length=200)
    hashed_password:  str           = Field(max_length=200)
    role:             UserRole      = Field(default=UserRole.REQUESTER)
    department_id:    Optional[UUID]= Field(default=None, foreign_key="departments.id")
    phone:            Optional[str] = Field(default=None, max_length=20)
    is_active:        bool          = Field(default=True)
    is_superuser:     bool          = Field(default=False)
    delegate_id:      Optional[UUID]= Field(default=None, foreign_key="users.id")
    site_id:          Optional[UUID]= Field(default=None, foreign_key="sites.id")

    site:           Optional["Site"]       = Relationship(back_populates="users")
    department:     Optional[Department]    = Relationship(back_populates="users")
    created_pos:    List["PurchaseOrder"]   = Relationship(
        back_populates="requester",
        sa_relationship_kwargs={"foreign_keys": "[PurchaseOrder.requester_id]"},
    )
    approval_steps: List["ApprovalStep"]   = Relationship(
        back_populates="approver",
        sa_relationship_kwargs={"foreign_keys": "[ApprovalStep.approver_id]"},
    )
    audit_logs:     List["AuditLog"]       = Relationship(back_populates="actor")


# ── Approval Chain Config ─────────────────────────────────────────────────────

class ApprovalChain(TimestampMixin, table=True):
    __tablename__ = "approval_chains"

    id:              UUID             = Field(default_factory=uuid4, primary_key=True)
    name:            str              = Field(max_length=200)
    po_category:     str              = Field(max_length=100)
    min_amount:      Decimal          = Field(sa_column=Column(Numeric(15, 2)), default=0)
    max_amount:      Optional[Decimal]= Field(sa_column=Column(Numeric(15, 2)), default=None)
    required_levels: int              = Field(default=2)
    sla_hours:       int              = Field(default=24)
    is_active:       bool             = Field(default=True)


# ── Purchase Order ────────────────────────────────────────────────────────────

class PurchaseOrder(TimestampMixin, table=True):
    __tablename__ = "purchase_orders"

    id:               UUID       = Field(default_factory=uuid4, primary_key=True)
    po_number:        str        = Field(max_length=30, unique=True, index=True)
    status:           POStatus   = Field(default=POStatus.DRAFT, index=True)
    priority:         POPriority = Field(default=POPriority.NORMAL)

    requester_id:     UUID           = Field(foreign_key="users.id")
    department_id:    Optional[UUID] = Field(default=None, foreign_key="departments.id")
    project_id:       Optional[UUID] = Field(default=None, foreign_key="projects.id")
    vendor_id:        UUID           = Field(foreign_key="vendors.id")

    po_category:      str            = Field(max_length=100, default="material")
    po_type:          Optional[str]  = Field(default=None, max_length=20)
    sub_category:     Optional[str]  = Field(default=None, max_length=100)
    site_id:          Optional[UUID] = Field(default=None, foreign_key="sites.id")
    budget_category_id: Optional[UUID] = Field(default=None, foreign_key="budget_categories.id")
    exceeds_budget:        bool           = Field(default=False)
    budget_authorized:     bool           = Field(default=False)
    budget_authorized_at:  Optional[datetime] = Field(default=None)
    description:      str            = Field(sa_column=Column(Text))
    delivery_address: str            = Field(sa_column=Column(Text))
    required_by:      datetime
    payment_terms:    Optional[str]  = Field(default=None, max_length=100)

    subtotal:         Decimal = Field(sa_column=Column(Numeric(15, 2)), default=0)
    gst_amount:       Decimal = Field(sa_column=Column(Numeric(15, 2)), default=0)
    total_amount:     Decimal = Field(sa_column=Column(Numeric(15, 2)), default=0)

    current_level:    int           = Field(default=0)
    required_levels:  int           = Field(default=2)
    rejection_reason:   Optional[str] = Field(default=None, sa_column=Column(Text))
    return_reason:      Optional[str] = Field(default=None, sa_column=Column(Text))
    penalty_clauses:    Optional[str] = Field(default=None, sa_column=Column(Text))
    delivery_terms:     Optional[str] = Field(default=None, sa_column=Column(Text))
    warranty_terms:     Optional[str] = Field(default=None, sa_column=Column(Text))
    special_conditions: Optional[str] = Field(default=None, sa_column=Column(Text))

    submitted_at:     Optional[datetime] = Field(default=None)
    approved_at:      Optional[datetime] = Field(default=None)
    rejected_at:      Optional[datetime] = Field(default=None)
    closed_at:        Optional[datetime] = Field(default=None)

    site:            Optional["Site"] = Relationship(back_populates="purchase_orders")
    requester:       User       = Relationship(
        back_populates="created_pos",
        sa_relationship_kwargs={"foreign_keys": "[PurchaseOrder.requester_id]"},
    )
    department:      Optional[Department] = Relationship(back_populates="purchase_orders")
    project:         Optional[Project]    = Relationship(back_populates="purchase_orders")
    vendor:          Vendor               = Relationship(back_populates="purchase_orders")
    line_items:      List["POLineItem"]   = Relationship(back_populates="purchase_order")
    approval_steps:  List["ApprovalStep"] = Relationship(back_populates="purchase_order")
    audit_logs:      List["AuditLog"]     = Relationship(back_populates="purchase_order")
    attachments:     List["POAttachment"] = Relationship(back_populates="purchase_order")


# ── PO Line Items ─────────────────────────────────────────────────────────────

class POLineItem(SQLModel, table=True):
    __tablename__ = "po_line_items"

    id:                UUID    = Field(default_factory=uuid4, primary_key=True)
    purchase_order_id: UUID    = Field(foreign_key="purchase_orders.id")
    sort_order:        int     = Field(default=0)
    description:       str     = Field(sa_column=Column(Text))
    unit_of_measure:   str     = Field(max_length=30, default="nos")
    quantity:          Decimal = Field(sa_column=Column(Numeric(12, 3)))
    unit_rate:         Decimal = Field(sa_column=Column(Numeric(15, 2)))
    amount:            Decimal = Field(sa_column=Column(Numeric(15, 2)))
    gst_percent:       Decimal = Field(sa_column=Column(Numeric(5, 2)), default=0)
    gst_amount:        Decimal = Field(sa_column=Column(Numeric(15, 2)), default=0)
    total:             Decimal = Field(sa_column=Column(Numeric(15, 2)))

    purchase_order: PurchaseOrder = Relationship(back_populates="line_items")


# ── Approval Steps ────────────────────────────────────────────────────────────

class ApprovalStep(TimestampMixin, table=True):
    __tablename__ = "approval_steps"

    id:                UUID           = Field(default_factory=uuid4, primary_key=True)
    purchase_order_id: UUID           = Field(foreign_key="purchase_orders.id", index=True)
    approver_id:       UUID           = Field(foreign_key="users.id")
    level:             int
    action:            ApprovalAction
    comments:          Optional[str]  = Field(default=None, sa_column=Column(Text))
    acted_at:          datetime       = Field(default_factory=datetime.utcnow)
    delegated_from_id: Optional[UUID] = Field(default=None, foreign_key="users.id")

    purchase_order: PurchaseOrder = Relationship(back_populates="approval_steps")
    approver:       User          = Relationship(
        back_populates="approval_steps",
        sa_relationship_kwargs={"foreign_keys": "[ApprovalStep.approver_id]"},  # ← FIXED
    )


# ── Attachments ───────────────────────────────────────────────────────────────

class POAttachment(TimestampMixin, table=True):
    __tablename__ = "po_attachments"

    id:                UUID = Field(default_factory=uuid4, primary_key=True)
    purchase_order_id: UUID = Field(foreign_key="purchase_orders.id")
    filename:          str  = Field(max_length=255)
    s3_key:            str  = Field(max_length=500)
    content_type:      str  = Field(max_length=100)
    size_bytes:        int  = Field(default=0)
    uploaded_by_id:    UUID = Field(foreign_key="users.id")

    purchase_order: PurchaseOrder = Relationship(back_populates="attachments")


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id:                UUID             = Field(default_factory=uuid4, primary_key=True)
    purchase_order_id: UUID             = Field(foreign_key="purchase_orders.id", index=True)
    actor_id:          UUID             = Field(foreign_key="users.id")
    action:            AuditAction
    from_status:       Optional[POStatus] = Field(default=None)
    to_status:         Optional[POStatus] = Field(default=None)
    comments:          Optional[str]      = Field(default=None, sa_column=Column(Text))
    extra_data:        Optional[dict]     = Field(default=None, sa_column=Column(JSON))
    created_at:        datetime           = Field(default_factory=datetime.utcnow)

    purchase_order: PurchaseOrder = Relationship(back_populates="audit_logs")
    actor:          User          = Relationship(back_populates="audit_logs")