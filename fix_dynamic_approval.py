"""
fix_dynamic_approval.py
=======================
Fixes two issues:
1. MD email shows which site the PO is from
2. Approval chain skips levels with no approvers for that site
   (e.g. Nepal has L1+L2+MD but no L3/L4/FINANCE — after L2 goes to MD)

Run from project ROOT:
    docker-compose exec app python fix_dynamic_approval.py
"""
import os

OK  = lambda s: print(f"  ✅  {s}")
ERR = lambda s: print(f"  ❌  {s}")
HDR = lambda s: print(f"\n{'─'*60}\n  {s}\n{'─'*60}")

def patch(path, old, new, label):
    if not os.path.exists(path):
        ERR(f"{path} not found"); return False
    content = open(path, encoding="utf-8").read()
    if old in content:
        open(path, "w", encoding="utf-8").write(content.replace(old, new))
        OK(label); return True
    ERR(f"Pattern not found — '{label}'"); return False


# ══════════════════════════════════════════════════════════════════════════════
# 1. po_service.py — fix required_levels to count actual site approvers
#    in the correct order and include MD as final level
# ══════════════════════════════════════════════════════════════════════════════
HDR("1 / 3  →  app/services/po_service.py  (dynamic levels)")

patch(
    "app/services/po_service.py",
    '''       # Dynamic levels based on site approvers + MD Owner as final
        required_levels = 4  # default
        if getattr(data, 'site_id', None):
            from app.models.models import User as _User
            from uuid import UUID as _UUID
            _approver_roles = ['L1_APPROVER','L2_APPROVER','L3_APPROVER','L4_APPROVER','FINANCE']
            _site_approvers = (await session.execute(
                select(_User).where(
                    _User.site_id == _UUID(str(data.site_id)),
                    _User.is_active == True,
                    _User.role.in_(_approver_roles)
                )
            )).scalars().all()
            # +1 for MD Owner as final level
            required_levels = len(_site_approvers) + 1 if _site_approvers else 4''',
    '''        # Dynamic levels based on site approvers present + MD Owner as final
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
            required_levels = _levels_with_approvers + 1 if _levels_with_approvers else 2''',
    "po_service.py — required_levels counts only roles that have approvers"
)


# ══════════════════════════════════════════════════════════════════════════════
# 2. approval_engine.py — get_next_trigger should use approve_final
#    when next level has no approvers for this site
#    Also fix can_user_approve for MD to allow at any final level
# ══════════════════════════════════════════════════════════════════════════════
HDR("2 / 3  →  app/services/approval_engine.py  (MD can approve at correct level)")

patch(
    "app/services/approval_engine.py",
    '''        # MD Owner approves at level 5 (l5_approved) or as final
        if user.role.value in ['md_owner', 'MD_OWNER']:
            if po.status in [POStatus.L5_APPROVED, POStatus.L4_APPROVED, POStatus.L3_APPROVED]:
                return True, "ok"
            if po.status == POStatus.SUBMITTED and po.required_levels == 1:
                return True, "ok"
            return False, "MD Owner approves at the final level only"''',
    '''        # MD Owner approves at the final level (whatever that is for this PO)
        if user.role.value in ['md_owner', 'MD_OWNER']:
            # Build the expected status at the final level
            level_to_status = {
                1: POStatus.SUBMITTED,
                2: POStatus.L1_APPROVED,
                3: POStatus.L2_APPROVED,
                4: POStatus.L3_APPROVED,
                5: POStatus.L4_APPROVED,
                6: POStatus.L5_APPROVED,
            }
            # The MD acts at required_levels (last level)
            expected_status = level_to_status.get(po.required_levels)
            if expected_status and po.status == expected_status:
                return True, "ok"
            if user.id == po.requester_id:
                return False, "You cannot approve your own PO"
            return False, f"PO is not at MD approval level yet (current: {po.status.value}, needs: {expected_status.value if expected_status else 'unknown'})"''',
    "approval_engine.py — MD approves at correct dynamic final level"
)


# ══════════════════════════════════════════════════════════════════════════════
# 3. notifications.py — add site name to MD email
# ══════════════════════════════════════════════════════════════════════════════
HDR("3 / 3  →  app/tasks/notifications.py  (site name in emails)")

# First add site to _get_po query
patch(
    "app/tasks/notifications.py",
    '''    async with S() as s:
        r = await s.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id)
            .options(selectinload(PurchaseOrder.vendor), selectinload(PurchaseOrder.requester),
                     selectinload(PurchaseOrder.audit_logs)))
        return r.scalar_one_or_none()''',
    '''    async with S() as s:
        from sqlalchemy.orm import selectinload as _sil
        r = await s.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id)
            .options(
                _sil(PurchaseOrder.vendor),
                _sil(PurchaseOrder.requester),
                _sil(PurchaseOrder.audit_logs),
                _sil(PurchaseOrder.site),
            ))
        return r.scalar_one_or_none()''',
    "notifications.py — site loaded in _get_po"
)

# Update _card to include site info
patch(
    "app/tasks/notifications.py",
    '''def _card(po_number, vendor, amount, category, requester, url):
    return f"""<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:16px;margin:16px 0">
    <a href="{url}" style="color:#2563EB;font-family:monospace;font-weight:700">{po_number}</a>
    <table style="width:100%;margin-top:12px;font-size:0.85rem"><tr>
      <td><b>Vendor:</b> {vendor}</td><td><b>Category:</b> {category.replace("_"," ").title()}</td>
    </tr><tr>
      <td><b>Requester:</b> {requester}</td>
      <td><b>Amount:</b> <span style="color:#2563EB;font-weight:800">Rs.{float(amount):,.2f}</span></td>
    </tr></table></div>''',
    '''def _card(po_number, vendor, amount, category, requester, url, site=None):
    site_row = f"<tr><td><b>Site:</b> {site}</td><td></td></tr>" if site else ""
    return f"""<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:16px;margin:16px 0">
    <a href="{url}" style="color:#2563EB;font-family:monospace;font-weight:700">{po_number}</a>
    <table style="width:100%;margin-top:12px;font-size:0.85rem"><tr>
      <td><b>Vendor:</b> {vendor}</td><td><b>Category:</b> {category.replace("_"," ").title()}</td>
    </tr><tr>
      <td><b>Requester:</b> {requester}</td>
      <td><b>Amount:</b> <span style="color:#2563EB;font-weight:800">Rs.{float(amount):,.2f}</span></td>
    </tr>{site_row}</table></div>''',
    "notifications.py — site added to email card"
)

# Update all _card() calls to pass site
path = "app/tasks/notifications.py"
content = open(path, encoding="utf-8").read()
# Replace _card calls to include site
old_card_call = '_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url)'
new_card_call = '_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url, site=po.site.name if po.site else None)'
if old_card_call in content:
    count = content.count(old_card_call)
    content = content.replace(old_card_call, new_card_call)
    open(path, "w", encoding="utf-8").write(content)
    OK(f"notifications.py — site passed to all {count} _card() calls")
else:
    ERR("_card() call pattern not found in notifications.py")


print("""
╔══════════════════════════════════════════════════════════╗
║  Done! Now run:                                          ║
║                                                          ║
║  docker-compose restart app worker                       ║
║                                                          ║
║  Then test with Nepal site:                              ║
║  • Create PO → submit → L1 approves → L2 approves       ║
║  • MD should get email with site name shown              ║
║  • MD should see approve button after L2 approves        ║
╚══════════════════════════════════════════════════════════╝
""")
