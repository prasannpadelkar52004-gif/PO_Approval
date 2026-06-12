"""
fix_site_approval.py
====================
Fixes approval and email to be site-scoped:
  1. approval_engine.py  — can_user_approve checks site match
  2. notifications.py    — send_approval_request_email filters by PO site
Run from project ROOT:
    docker-compose exec app python fix_site_approval.py
"""
import os

OK  = lambda s: print(f"  ✅  {s}")
ERR = lambda s: print(f"  ❌  {s}")
HDR = lambda s: print(f"\n{'─'*60}\n  {s}\n{'─'*60}")

def patch(path, old, new, label):
    if not os.path.exists(path):
        ERR(f"{path} not found")
        return False
    content = open(path, encoding="utf-8").read()
    if old in content:
        open(path, "w", encoding="utf-8").write(content.replace(old, new))
        OK(label)
        return True
    ERR(f"Pattern not found — '{label}'")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 1. approval_engine.py — add site check to can_user_approve
# ══════════════════════════════════════════════════════════════════════════════
HDR("1 / 2  →  app/services/approval_engine.py")

patch(
    "app/services/approval_engine.py",
    '''        role_level_map = {
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
        return True, "ok"''',
    '''        role_level_map = {
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
        # Site check — approver must belong to the same site as the PO
        if po.site_id and user.site_id and po.site_id != user.site_id:
            return False, "You are not assigned to this PO's site"
        return True, "ok"''',
    "approval_engine.py — site check added to can_user_approve"
)


# ══════════════════════════════════════════════════════════════════════════════
# 2. notifications.py — filter approvers by PO site in send_approval_request_email
# ══════════════════════════════════════════════════════════════════════════════
HDR("2 / 2  →  app/tasks/notifications.py")

patch(
    "app/tasks/notifications.py",
    '''async def _get_approvers_for_level(level):
    """Get approvers for a specific level only."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.models.models import User, UserRole
    roles = {
        1: UserRole.L1_APPROVER,
        2: UserRole.L2_APPROVER,
        3: UserRole.L3_APPROVER,
        4: UserRole.L4_APPROVER,
        5: UserRole.FINANCE,
        6: UserRole.MD_OWNER,
    }
    role = roles.get(level)
    if not role:
        return []
    engine = create_async_engine(settings.DATABASE_URL)
    S = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as s:
        r = await s.execute(select(User).where(User.role == role, User.is_active == True))
        return r.scalars().all()''',
    '''async def _get_approvers_for_level(level, site_id=None):
    """Get approvers for a specific level, optionally filtered by site."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.models.models import User, UserRole
    from uuid import UUID
    roles = {
        1: UserRole.L1_APPROVER,
        2: UserRole.L2_APPROVER,
        3: UserRole.L3_APPROVER,
        4: UserRole.L4_APPROVER,
        5: UserRole.FINANCE,
        6: UserRole.MD_OWNER,
    }
    role = roles.get(level)
    if not role:
        return []
    engine = create_async_engine(settings.DATABASE_URL)
    S = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as s:
        q = select(User).where(User.role == role, User.is_active == True)
        if site_id:
            # Try site-specific first
            site_uuid = UUID(str(site_id)) if not isinstance(site_id, UUID) else site_id
            r = await s.execute(q.where(User.site_id == site_uuid))
            approvers = r.scalars().all()
            # Fall back to approvers with no site assigned (global approvers)
            if not approvers:
                r = await s.execute(q.where(User.site_id == None))
                approvers = r.scalars().all()
            # For MD_OWNER level, also include MD owners from any site
            if not approvers and role == UserRole.MD_OWNER:
                r = await s.execute(select(User).where(User.role == role, User.is_active == True))
                approvers = r.scalars().all()
            return approvers
        r = await s.execute(q)
        return r.scalars().all()''',
    "notifications.py — _get_approvers_for_level now site-aware"
)

# Update send_approval_request_email to pass site_id
patch(
    "app/tasks/notifications.py",
    '''    approvers = await _get_approvers_for_level(level)''',
    '''    approvers = await _get_approvers_for_level(level, site_id=getattr(po, "site_id", None))''',
    "notifications.py — site_id passed to _get_approvers_for_level"
)

print("""
╔══════════════════════════════════════════════════════════╗
║  Done! Now run:                                          ║
║                                                          ║
║  docker-compose restart app worker                       ║
║                                                          ║
║  Then test: Nepal requester creates PO, submits it →     ║
║  only Nepal L1 approvers see approve button + get email  ║
╚══════════════════════════════════════════════════════════╝
""")
