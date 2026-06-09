"""
Tests for the Approval Engine state machine.
Run with: pytest tests/unit/test_approval_engine.py -v

Uses simple namespace objects instead of SQLModel table instances
so tests run without a DB connection or mapper configuration.
"""
import pytest
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime

from app.models.models import POStatus, UserRole, ApprovalChain
from app.services.approval_engine import POStateMachine, ApprovalEngine


def make_po(status: POStatus = POStatus.DRAFT, required_levels: int = 2):
    return SimpleNamespace(
        id=uuid4(),
        po_number="PO-2026-0001",
        status=status,
        requester_id=uuid4(),
        vendor_id=uuid4(),
        po_category="material",
        description="Test PO",
        delivery_address="Site A",
        required_by=datetime(2026, 6, 1),
        subtotal=Decimal("100000"),
        gst_amount=Decimal("18000"),
        total_amount=Decimal("118000"),
        required_levels=required_levels,
        current_level=0,
    )


def make_user(role: UserRole, user_id=None):
    return SimpleNamespace(
        id=user_id or uuid4(),
        email=f"{role.value}@test.com",
        full_name=f"Test {role.value}",
        hashed_password="hashed",
        role=role,
        is_active=True,
    )


# ── State machine tests ───────────────────────────────────────────────────────

class TestPOStateMachine:

    def test_draft_to_submitted(self):
        po = make_po(POStatus.DRAFT)
        sm = POStateMachine(po)
        sm.submit()
        assert sm.current_state == POStatus.SUBMITTED

    def test_submitted_to_l1_approved(self):
        po = make_po(POStatus.SUBMITTED)
        sm = POStateMachine(po)
        sm.approve_l1()
        assert sm.current_state == POStatus.L1_APPROVED

    def test_submitted_to_rejected(self):
        po = make_po(POStatus.SUBMITTED)
        sm = POStateMachine(po)
        sm.reject()
        assert sm.current_state == POStatus.REJECTED

    def test_submitted_to_returned(self):
        po = make_po(POStatus.SUBMITTED)
        sm = POStateMachine(po)
        sm.return_po()
        assert sm.current_state == POStatus.RETURNED

    def test_returned_can_resubmit(self):
        po = make_po(POStatus.RETURNED)
        sm = POStateMachine(po)
        sm.submit()
        assert sm.current_state == POStatus.SUBMITTED

    def test_full_4_level_flow(self):
        po = make_po(POStatus.DRAFT, required_levels=4)
        sm = POStateMachine(po)
        sm.submit()
        assert sm.current_state == POStatus.SUBMITTED
        sm.approve_l1()
        assert sm.current_state == POStatus.L1_APPROVED
        sm.approve_l2()
        assert sm.current_state == POStatus.L2_APPROVED
        sm.approve_l3()
        assert sm.current_state == POStatus.L3_APPROVED
        sm.approve_l4()
        assert sm.current_state == POStatus.APPROVED

    def test_approve_final_skips_remaining_levels(self):
        po = make_po(POStatus.L1_APPROVED, required_levels=2)
        sm = POStateMachine(po)
        sm.approve_final()
        assert sm.current_state == POStatus.APPROVED

    def test_cannot_submit_from_approved(self):
        po = make_po(POStatus.APPROVED)
        sm = POStateMachine(po)
        with pytest.raises(Exception):
            sm.submit()

    def test_draft_can_be_cancelled(self):
        po = make_po(POStatus.DRAFT)
        sm = POStateMachine(po)
        sm.cancel()
        assert sm.current_state == POStatus.CANCELLED


# ── Approval engine logic tests ───────────────────────────────────────────────

class TestApprovalEngine:

    def test_resolve_levels_by_amount(self):
        chains = [
            SimpleNamespace(
                po_category="material",
                min_amount=Decimal("0"),
                max_amount=Decimal("100000"),
                required_levels=2, is_active=True,
            ),
            SimpleNamespace(
                po_category="material",
                min_amount=Decimal("100001"),
                max_amount=None,
                required_levels=4, is_active=True,
            ),
        ]
        assert ApprovalEngine.resolve_required_levels(
            "material", Decimal("50000"), chains) == 2
        assert ApprovalEngine.resolve_required_levels(
            "material", Decimal("500000"), chains) == 4

    def test_get_next_trigger_not_final(self):
        trigger = ApprovalEngine.get_next_trigger(POStatus.SUBMITTED, required_levels=4)
        assert trigger == "approve_l1"

    def test_get_next_trigger_is_final(self):
        trigger = ApprovalEngine.get_next_trigger(POStatus.SUBMITTED, required_levels=1)
        assert trigger == "approve_final"

    def test_cannot_approve_own_po(self):
        requester_id = uuid4()
        po = make_po(POStatus.SUBMITTED)
        po.requester_id = requester_id

        user = make_user(UserRole.L1_APPROVER, user_id=requester_id)
        can, reason = ApprovalEngine.can_user_approve(user, po)
        assert not can
        assert "own PO" in reason

    def test_wrong_level_cannot_approve(self):
        po = make_po(POStatus.SUBMITTED)  # waiting for L1
        l2_user = make_user(UserRole.L2_APPROVER)
        can, reason = ApprovalEngine.can_user_approve(l2_user, po)
        assert not can

    def test_correct_level_can_approve(self):
        po = make_po(POStatus.SUBMITTED)  # waiting for L1
        l1_user = make_user(UserRole.L1_APPROVER)
        can, reason = ApprovalEngine.can_user_approve(l1_user, po)
        assert can

    def test_admin_can_always_approve(self):
        po = make_po(POStatus.L3_APPROVED)
        admin = make_user(UserRole.ADMIN)
        can, reason = ApprovalEngine.can_user_approve(admin, po)
        assert can
