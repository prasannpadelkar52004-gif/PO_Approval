"""
ARQ Background Tasks - Email Notifications
All approvers notified when PO submitted, but approval flow is sequential L1->L2->L3->L4
"""
import logging
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from arq.connections import RedisSettings
from app.core.config import settings

logger = logging.getLogger(__name__)

async def send_email(to, subject, html_body):
    if not settings.SMTP_HOST:
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))
    try:
        await aiosmtplib.send(msg, hostname=settings.SMTP_HOST, port=settings.SMTP_PORT,
            username=settings.SMTP_USER, password=settings.SMTP_PASSWORD,
            use_tls=False, start_tls=True)
        logger.info("Email sent to %s", to)
    except Exception as e:
        logger.error("Email failed to %s: %s", to, e)

def _base(content):
    return f"""<html><body style="font-family:Arial;max-width:600px;margin:auto;padding:20px">
    <div style="background:#0F1B2D;padding:16px;border-radius:8px 8px 0 0">
      <h2 style="color:white;margin:0">P E E I - PO Approval System</h2>
    </div>
    <div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px">
      {content}
      <hr style="margin:20px 0">
      <p style="color:#888;font-size:12px">Automated notification. Do not reply.</p>
    </div></body></html>"""

def _card(po_number, vendor, amount, category, requester, url, site=None):
    site_row = f"<tr><td><b>Site:</b> {site}</td><td></td></tr>" if site else ""
    return f"""<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:16px;margin:16px 0">
    <a href="{url}" style="color:#2563EB;font-family:monospace;font-weight:700">{po_number}</a>
    <table style="width:100%;margin-top:12px;font-size:0.85rem"><tr>
      <td><b>Vendor:</b> {vendor}</td><td><b>Category:</b> {category.replace("_"," ").title()}</td>
    </tr><tr>
      <td><b>Requester:</b> {requester}</td>
      <td><b>Amount:</b> <span style="color:#2563EB;font-weight:800">Rs.{float(amount):,.2f}</span></td>
    </tr>{site_row}</table></div>"""

def _btn(text, url, color="#2563EB"):
    return f'<p style="text-align:center"><a href="{url}" style="background:{color};color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">{text}</a></p>'

async def _get_po(po_id):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker, selectinload
    from sqlalchemy import select
    from app.models.models import PurchaseOrder
    engine = create_async_engine(settings.DATABASE_URL)
    S = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as s:
        from sqlalchemy.orm import selectinload as _sil
        r = await s.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id)
            .options(
                _sil(PurchaseOrder.vendor),
                _sil(PurchaseOrder.requester),
                _sil(PurchaseOrder.audit_logs),
                _sil(PurchaseOrder.site),
            ))
        return r.scalar_one_or_none()

async def _get_all_approvers(site_id=None):
    """Get active approvers for a specific site (or all if no site given)."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.models.models import User, UserRole
    from uuid import UUID
    engine = create_async_engine(settings.DATABASE_URL)
    S = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as s:
        q = select(User).where(
            User.role.in_([UserRole.L1_APPROVER, UserRole.L2_APPROVER,
                           UserRole.L3_APPROVER, UserRole.L4_APPROVER, UserRole.FINANCE]),
            User.is_active == True
        )
        if site_id:
            site_uuid = UUID(str(site_id)) if not isinstance(site_id, UUID) else site_id
            q = q.where(User.site_id == site_uuid)
        r = await s.execute(q)
        return r.scalars().all()

async def _get_approvers_for_level(level, site_id=None, po_required_levels=None):
    """
    Get approvers for a specific level, scoped to the PO's site.
    MD_OWNER is always global (no site filter) and acts at the final level.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.models.models import User, UserRole
    from uuid import UUID

    # Map level number to role
    # MD is always the final level — determined by po_required_levels
    if po_required_levels and level == po_required_levels:
        # Final level = MD
        role = UserRole.MD_OWNER
    else:
        role_map = {
            1: UserRole.L1_APPROVER,
            2: UserRole.L2_APPROVER,
            3: UserRole.L3_APPROVER,
            4: UserRole.L4_APPROVER,
            5: UserRole.FINANCE,
        }
        role = role_map.get(level)
        if not role:
            return []

    engine = create_async_engine(settings.DATABASE_URL)
    S = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as s:
        if role == UserRole.MD_OWNER:
            # MD is global — no site filter
            r = await s.execute(select(User).where(
                User.role == UserRole.MD_OWNER,
                User.is_active == True
            ))
            return r.scalars().all()

        if site_id:
            site_uuid = UUID(str(site_id)) if not isinstance(site_id, UUID) else site_id
            r = await s.execute(select(User).where(
                User.role == role,
                User.is_active == True,
                User.site_id == site_uuid
            ))
            approvers = r.scalars().all()
            return approvers

        r = await s.execute(select(User).where(User.role == role, User.is_active == True))
        return r.scalars().all()


async def send_po_created_email(ctx, po_id: str) -> None:
    """Notify requester + ALL approvers when PO is created."""
    po = await _get_po(po_id)
    if not po:
        return
    url = f"{settings.APP_BASE_URL}/pos/{po_id}"

    # Notify requester
    body = f"""<h2>PO Created Successfully</h2>
    <p>Hello <b>{po.requester.full_name}</b>,</p>
    <p>Your Purchase Order has been saved as <b>Draft</b>. Submit it for approval when ready.</p>
    {_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url, site=po.site.name if po.site else None)}
    {_btn("View and Submit PO", url)}"""
    await send_email(po.requester.email, f"PO {po.po_number} Created", _base(body))
    logger.info("PO created email -> %s", po.requester.email)


async def send_approval_request_email(ctx, po_id: str, level: int) -> None:
    """Notify ONLY the current level approvers."""
    po = await _get_po(po_id)
    if not po:
        logger.error("PO not found: %s", po_id)
        return

    approvers = await _get_approvers_for_level(level, site_id=getattr(po, "site_id", None), po_required_levels=po.required_levels)
    if not approvers:
        logger.warning("No active L%d approvers found for PO %s", level, po_id)
        return

    url = f"{settings.APP_BASE_URL}/pos/{po_id}"
    level_labels = {
        1: "L1 - Site Manager",
        2: "L2 - Project Manager",
        3: "L3 - GM / Finance",
        4: "L4 - Approver",
        5: "L5 - Finance",
        6: "L6 - MD / Owner",
    }
    label = level_labels.get(level, f"Level {level}")

    for approver in approvers:
        body = f"""
        <h2 style="color:#2563EB;">Action Required: Your Approval Needed</h2>
        <p>Hello <strong>{approver.full_name}</strong>,</p>
        <p>A Purchase Order is now at your level (<strong>{label}</strong>) and requires your approval.</p>
        {_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url, site=po.site.name if po.site else None)}
        {_btn("Review and Approve PO", url, "#2563EB")}
        """
        await send_email(
            approver.email,
            f"[Action Required] {po.po_number} needs your approval ({label})",
            _base(body)
        )
        logger.info("Approval request L%d sent to %s for PO %s", level, approver.email, po_id)  


async def send_status_update_email(ctx, po_id: str, action: str, new_status: str) -> None:
    """Notify requester + ALL approvers of status change."""
    po = await _get_po(po_id)
    if not po:
        return
    url = f"{settings.APP_BASE_URL}/pos/{po_id}"
    logs = sorted(po.audit_logs, key=lambda l: l.created_at, reverse=True)
    comment = logs[0].comments if logs and logs[0].comments else ""
    cb = f'<p style="background:#F8FAFC;border-left:4px solid #94A3B8;padding:10px;font-style:italic">"{comment}"</p>' if comment else ""

    if action == "approve" and new_status == "approved":
        subj = f"Approved: {po.po_number} Fully Approved!"
        color, title = "#16A34A", "PO Fully Approved!"
        msg, btn = "Your PO has been fully approved by all levels.", "View Approved PO"
    elif action == "approve":
        lvl = new_status.replace("_approved", "").upper()
        subj = f"Update: {po.po_number} Approved at {lvl}"
        color, title = "#2563EB", f"PO Approved at {lvl}"
        msg, btn = f"PO approved at <b>{lvl}</b> level, moving to next approver.", "View PO Status"
    elif action == "reject":
        subj = f"Rejected: {po.po_number}"
        color, title = "#DC2626", "PO Rejected"
        msg, btn = "The PO has been rejected.", "View Details"
    elif action == "return":
        subj = f"Returned: {po.po_number}"
        color, title = "#D97706", "PO Returned for Revision"
        msg, btn = "The PO was returned for revision.", "Review and Resubmit"
    else:
        return

    # Notify requester
    body = f"""<h2 style="color:{color}">{title}</h2>
    <p>Hello <b>{po.requester.full_name}</b>,</p>
    <p>{msg}</p>
    {_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url, site=po.site.name if po.site else None)}
    {cb}{_btn(btn, url, color)}"""
    await send_email(po.requester.email, subj, _base(body))

    # Also notify same-site approvers of status change
    all_approvers = await _get_all_approvers(site_id=getattr(po, "site_id", None))
    for approver in all_approvers:
        body_approver = f"""<h2 style="color:{color}">{title}</h2>
        <p>Hello <b>{approver.full_name}</b>,</p>
        <p>Status update on PO: {msg}</p>
        {_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url, site=po.site.name if po.site else None)}
        {cb}{_btn("View PO Details", url, color)}"""
        await send_email(approver.email, subj, _base(body_approver))

    logger.info("Status update %s sent to requester + all approvers for %s", action, po_id)


async def send_reminder_email(ctx, po_id: str, level: int, hours_overdue: int) -> None:
    """Remind only the current level approvers."""
    await send_approval_request_email(ctx, po_id, level)


def _redis(url):
    url = url.replace("redis://", "")
    if "@" in url:
        _, url = url.split("@", 1)
    h, p = url.split(":") if ":" in url else (url, "6379")
    return RedisSettings(host=h, port=int(p))




async def send_budget_exceed_email(ctx, po_id: str) -> None:
    """Notify MD that a PO has exceeded its budget."""
    from uuid import UUID
    po = await _get_po(UUID(po_id))
    if not po:
        return

    # Get MD owners
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.models.models import User, UserRole
    engine = create_async_engine(settings.DATABASE_URL)
    S = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as s:
        r = await s.execute(select(User).where(
            User.role == UserRole.MD_OWNER, User.is_active == True
        ))
        mds = r.scalars().all()

    url = f"{settings.APP_BASE_URL}/pos/{po_id}"
    site_name = po.site.name if po.site else "Unknown Site"

    for md in mds:
        body = f"""
        <h2 style="color:#DC2626;">⚠️ Budget Exceeded — Action Required</h2>
        <p>Hello <strong>{md.full_name}</strong>,</p>
        <p>A Purchase Order has been created that <strong>exceeds the available budget</strong> for <strong>{site_name}</strong>.</p>
        {_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url, site=site_name)}
        <p style="background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;padding:12px;color:#DC2626;">
          <strong>Action Required:</strong> Please review this PO and authorize or reject the extra spending.
        </p>
        {_btn("Review & Authorize Extra Spend", url, "#DC2626")}
        """
        await send_email(
            md.email,
            f"[Budget Exceeded] {po.po_number} — {site_name} needs authorization",
            _base(body)
        )
        logger.info("Budget exceed email sent to MD %s for PO %s", md.email, po_id)


async def send_budget_authorized_email(ctx, po_id: str) -> None:
    """Notify requester that their PO budget has been authorized by MD."""
    from uuid import UUID
    po = await _get_po(UUID(po_id))
    if not po:
        return

    url = f"{settings.APP_BASE_URL}/pos/{po_id}"
    site_name = po.site.name if po.site else "Unknown Site"

    body = f"""
    <h2 style="color:#16A34A;">✅ Budget Authorized — You Can Now Submit</h2>
    <p>Hello <strong>{po.requester.full_name}</strong>,</p>
    <p>The MD has <strong>authorized the extra budget spending</strong> for your Purchase Order.</p>
    {_card(po.po_number, po.vendor.name, po.total_amount, po.po_category, po.requester.full_name, url, site=site_name)}
    <p style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:8px;padding:12px;color:#16A34A;">
      Your PO is now ready to be submitted for approval.
    </p>
    {_btn("Submit PO for Approval", url, "#16A34A")}
    """
    await send_email(
        po.requester.email,
        f"[Authorized] {po.po_number} — Budget approved, please submit for approval",
        _base(body)
    )
    logger.info("Budget authorized email sent to requester %s for PO %s", po.requester.email, po_id)

class WorkerSettings:
    functions = [send_po_created_email, send_approval_request_email, send_status_update_email, send_reminder_email, send_budget_exceed_email, send_budget_authorized_email]
    redis_settings = _redis(settings.REDIS_URL)
    max_jobs = 10
    job_timeout = 300
