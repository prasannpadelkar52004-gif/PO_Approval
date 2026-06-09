"""
Approval Engine — PO State Machine
====================================
Uses the `transitions` library to manage PO lifecycle.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from transitions import Machine

from app.models.models import (
    POStatus, ApprovalAction, AuditAction,
    PurchaseOrder, ApprovalStep, ApprovalChain, AuditLog, User
)


# ── State machine definition ──────────────────────────────────────────────────

STATES = [s.value for s in POStatus]

TRANSITIONS = [
    {"trigger": "submit",       "source": "draft",        "dest": "submitted"},
    {"trigger": "submit",       "source": "returned",     "dest": "submitted"},
    {"trigger": "approve_l1",   "source": "submitted",    "dest": "l1_approved"},
    {"trigger": "reject",       "source": "submitted",    "dest": "rejected"},
    {"trigger": "return_po",    "source": "submitted",    "dest": "returned"},
    {"trigger": "approve_l2",   "source": "l1_approved",  "dest": "l2_approved"},
    {"trigger": "reject",       "source": "l1_approved",  "dest": "rejected"},
    {"trigger": "return_po",    "source": "l1_approved",  "dest": "returned"},
    {"trigger": "approve_l3",   "source": "l2_approved",  "dest": "l3_approved"},
    {"trigger": "reject",       "source": "l2_approved",  "dest": "rejected"},
    {"trigger": "return_po",    "source": "l2_approved",  "dest": "returned"},
    {"trigger": "approve_l4",   "source": "l3_approved",  "dest": "l4_approved"},
    {"trigger": "reject",       "source": "l3_approved",  "dest": "rejected"},
    {"trigger": "return_po",    "source": "l3_approved",  "dest": "returned"},
    {"trigger": "approve_l5",   "source": "l4_approved",  "dest": "l5_approved"},
    {"trigger": "reject",       "source": "l4_approved",  "dest": "rejected"},
    {"trigger": "return_po",    "source": "l4_approved",  "dest": "returned"},
    {"trigger": "approve_l6",   "source": "l5_approved",  "dest": "approved"},
    {"trigger": "reject",       "source": "l5_approved",  "dest": "rejected"},
    {"trigger": "return_po",    "source": "l5_approved",  "dest": "returned"},
    {"trigger": "approve_final","source": "submitted",    "dest": "approved"},
    {"trigger": "approve_final","source": "l1_approved",  "dest": "approved"},
    {"trigger": "approve_final","source": "l2_approved",  "dest": "approved"},
    {"trigger": "approve_final","source": "l3_approved",  "dest": "approved"},
    {"trigger": "approve_final","source": "l4_approved",  "dest": "approved"},
    {"trigger": "approve_final","source": "l5_approved",  "dest": "approved"},
    {"trigger": "close",        "source": "approved",     "dest": "closed"},
    {"trigger": "cancel",       "source": "draft",        "dest": "cancelled"},
    {"trigger": "cancel",       "source": "returned",     "dest": "cancelled"},
]


class POStateMachine:
    def __init__(self, po):
        self.po = po
        self.machine = Machine(
            model=self,
            states=STATES,
            transitions=TRANSITIONS,
            initial=po.status.value,
            ignore_invalid_triggers=False,
            auto_transitions=False,
        )

    @property
    def current_state(self) -> POStatus:
        return POStatus(self.state)


# ── Approval Engine Service ───────────────────────────────────────────────────

class ApprovalEngine:

    @staticmethod
    def resolve_required_levels(
        po_category: str,
        total_amount: Decimal,
        chains: list[ApprovalChain],
    ) -> int:
        sorted_chains = sorted(
            [c for c in chains if c.po_category == po_category and c.is_active],
            key=lambda c: c.min_amount,
            reverse=True
        )
        for chain in sorted_chains:
            if total_amount >= chain.min_amount:
                if chain.max_amount is None or total_amount <= chain.max_amount:
                    return chain.required_levels
        return 2

    @staticmethod
    def get_next_trigger(current_status: POStatus, required_levels: int) -> str:
        """
        Determine which state machine trigger to call for an approval action.
        Automatically uses approve_final when the current level is the last one.
        """
        level_map = {
            POStatus.SUBMITTED:   (1, "approve_l1"),
            POStatus.L1_APPROVED: (2, "approve_l2"),
            POStatus.L2_APPROVED: (3, "approve_l3"),
            POStatus.L3_APPROVED: (4, "approve_l4"),
            POStatus.L4_APPROVED: (5, "approve_l5"),
            POStatus.L5_APPROVED: (6, "approve_l6"),
        }
        if current_status not in level_map:
            raise ValueError(f"Cannot approve from status: {current_status}")

        level, trigger = level_map[current_status]
        if level >= required_levels:
            return "approve_final"
        return trigger

    @staticmethod
    def can_user_approve(user: User, po: PurchaseOrder) -> tuple[bool, str]:
        """Returns (can_approve, reason)."""
        from app.models.models import UserRole

        # Admin can approve anywhere
        if user.role.value in ['admin', 'ADMIN']:
            return True, "ok"

        # MD Owner approves at level 5 (l5_approved) or as final
        if user.role.value in ['md_owner', 'MD_OWNER']:
            if po.status in [POStatus.L5_APPROVED, POStatus.L4_APPROVED, POStatus.L3_APPROVED]:
                return True, "ok"
            if po.status == POStatus.SUBMITTED and po.required_levels == 1:
                return True, "ok"
            return False, "MD Owner approves at the final level only"

        # Role-based mapping for site approvers
        role_level_map = {
            'L1_APPROVER': [POStatus.SUBMITTED],
            'L2_APPROVER': [POStatus.L1_APPROVED],
            'L3_APPROVER': [POStatus.L2_APPROVED],
            'L4_APPROVER': [POStatus.L3_APPROVED],
            'FINANCE':     [POStatus.L4_APPROVED],
        }
        allowed_statuses = role_level_map.get(user.role.value, [])
        if not allowed_statuses:
            return False, "Your role does not have approval permissions"
        if po.status not in allowed_statuses:
            return False, f"PO is not at your approval level (current: {po.status.value})"
        if user.id == po.requester_id:
            return False, "You cannot approve your own PO"
        return True, "ok"

    @staticmethod
    def build_audit_log(
        po: PurchaseOrder,
        actor: User,
        action: AuditAction,
        from_status: POStatus,
        to_status: POStatus,
        comments: Optional[str] = None,
    ) -> AuditLog:
        return AuditLog(
            purchase_order_id=po.id,
            actor_id=actor.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            comments=comments,
        )

    @staticmethod
    def build_approval_step(
        po: PurchaseOrder,
        approver: User,
        level: int,
        action: ApprovalAction,
        comments: Optional[str] = None,
        delegated_from_id: Optional[UUID] = None,
    ) -> ApprovalStep:
        return ApprovalStep(
            purchase_order_id=po.id,
            approver_id=approver.id,
            level=level,
            action=action,
            comments=comments,
            acted_at=datetime.utcnow(),
            delegated_from_id=delegated_from_id,
        )

    @staticmethod
    def current_approval_level(status: POStatus) -> int:
        """Returns the numeric level the PO is currently waiting at."""
        return {
            POStatus.SUBMITTED:   1,
            POStatus.L1_APPROVED: 2,
            POStatus.L2_APPROVED: 3,
            POStatus.L3_APPROVED: 4,
            POStatus.L4_APPROVED: 5,
            POStatus.L5_APPROVED: 6,
        }.get(status, 0)
