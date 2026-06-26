"""
HTML Routes — serves Jinja2 templates for the browser UI.
"""
from datetime import timedelta, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.models import (
    User, PurchaseOrder, POStatus, UserRole, Site,
    Vendor, Department, Project
)
from app.api.v1.deps import verify_password, create_access_token

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")


# ── Auth helper ───────────────────────────────────────────────────────────────

async def get_user_from_cookie(request: Request, session: AsyncSession) -> User | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from jose import jwt
        from app.core.config import settings
        payload = jwt.decode(token, settings.JWT_SECRET,
                             algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await session.execute(select(User).where(User.id == user_id, User.is_active == True))
        return result.scalar_one_or_none()
    except Exception:
        return None


def to_login():
    return RedirectResponse("/login", status_code=302)


# ── Login ─────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(User).where(User.email == username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Incorrect email or password"
        }, status_code=401)

    if not user.is_active:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Your account has been deactivated. Contact the administrator."
        }, status_code=401)

    token = create_access_token(str(user.id), timedelta(hours=8))
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, max_age=28800)
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


@router.get("/", response_class=HTMLResponse)
async def root(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    return RedirectResponse("/dashboard", status_code=302)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    now = datetime.utcnow()

    # ── Recent POs ────────────────────────────────────────────────────────────
    # Site filtering for dashboard
    dash_q = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.requester),
            selectinload(PurchaseOrder.vendor),
            selectinload(PurchaseOrder.site),
        )
        .order_by(desc(PurchaseOrder.created_at))
        .limit(8)
    )
    if user.role == UserRole.REQUESTER:
        dash_q = dash_q.where(PurchaseOrder.requester_id == user.id)
    elif user.role not in [UserRole.ADMIN, UserRole.MD_OWNER] and user.site_id:
        dash_q = dash_q.where(PurchaseOrder.site_id == user.site_id)

    r = await session.execute(dash_q)
    recent_pos_db = r.scalars().all()

    # ── Pending statuses for this role ────────────────────────────────────────
    pending_statuses = {
        UserRole.L1_APPROVER: [POStatus.SUBMITTED],
        UserRole.L2_APPROVER: [POStatus.L1_APPROVED],
        UserRole.L3_APPROVER: [POStatus.L2_APPROVED],
        UserRole.L4_APPROVER: [POStatus.L3_APPROVED],
        UserRole.FINANCE:     [POStatus.L4_APPROVED],
        UserRole.MD_OWNER:    [POStatus.L5_APPROVED],
        UserRole.ADMIN:       [POStatus.SUBMITTED, POStatus.L1_APPROVED,
                               POStatus.L2_APPROVED, POStatus.L3_APPROVED,
                               POStatus.L4_APPROVED, POStatus.L5_APPROVED],
    }.get(user.role, [])

    # ── Pending approvals ─────────────────────────────────────────────────────
    if pending_statuses:
        pdq = (select(PurchaseOrder).options(selectinload(PurchaseOrder.vendor), selectinload(PurchaseOrder.site)).where(PurchaseOrder.status.in_(pending_statuses)).order_by(desc(PurchaseOrder.created_at)).limit(10))
        if user.role == UserRole.MD_OWNER:
            # MD only sees POs where status matches their final approval level
            # i.e. po.status == level_status_map[po.required_levels]
            from sqlalchemy import case
            level_status_map = {
                1: POStatus.SUBMITTED,
                2: POStatus.L1_APPROVED,
                3: POStatus.L2_APPROVED,
                4: POStatus.L3_APPROVED,
                5: POStatus.L4_APPROVED,
                6: POStatus.L5_APPROVED,
            }
            from sqlalchemy import or_ as _or
            pdq = pdq.where(_or(
                *[
                    (PurchaseOrder.required_levels == lvl) & (PurchaseOrder.status == st)
                    for lvl, st in level_status_map.items()
                ]
            ))
        elif user.role not in [UserRole.ADMIN, UserRole.MD_OWNER] and user.site_id:
            pdq = pdq.where(PurchaseOrder.site_id == user.site_id)
        p = await session.execute(pdq)
        pending_db = p.scalars().all()
    else:
        pending_db = []

    # ── Stats ─────────────────────────────────────────────────────────────────
    # My open POs - only requester's own POs
    r1 = await session.execute(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.requester_id == user.id,
            PurchaseOrder.status.not_in([
                POStatus.APPROVED, POStatus.REJECTED,
                POStatus.CANCELLED, POStatus.CLOSED
            ])
        )
    )
    my_open = r1.scalar_one() or 0

    # Approved/Rejected stats — filter by site for non-admin users
    approved_q = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.status == "approved",
        func.extract("month", PurchaseOrder.approved_at) == now.month,
        func.extract("year",  PurchaseOrder.approved_at) == now.year,
    )
    rejected_q = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.status == "rejected",
        func.extract("month", PurchaseOrder.rejected_at) == now.month,
        func.extract("year",  PurchaseOrder.rejected_at) == now.year,
    )
    if user.role not in [UserRole.ADMIN, UserRole.MD_OWNER] and user.site_id:
        approved_q = approved_q.where(PurchaseOrder.site_id == user.site_id)
        rejected_q = rejected_q.where(PurchaseOrder.site_id == user.site_id)
    elif user.role == UserRole.REQUESTER:
        approved_q = approved_q.where(PurchaseOrder.requester_id == user.id)
        rejected_q = rejected_q.where(PurchaseOrder.requester_id == user.id)

    r2 = await session.execute(approved_q)
    approved_month = r2.scalar_one() or 0

    r3 = await session.execute(rejected_q)
    rejected_month = r3.scalar_one() or 0

    # ── Build simple dicts for templates ─────────────────────────────────────
    def po_dict(po, with_requester=False):
        d = {
            "id":           str(po.id),
            "po_number":    po.po_number,
            "status":       po.status.value,
            "priority":     po.priority.value,
            "po_category":  po.po_category,
            "total_amount": float(po.total_amount),
            "created_at":   po.created_at,
            "required_by":  po.required_by,
            "current_level":po.current_level,
            "vendor_name":  po.vendor.name if po.vendor else "—",
            "requester_id": str(po.requester_id),
            "site_name":    po.site.name if po.site else None,
        }
        if with_requester:
            d["requester_name"] = po.requester.full_name if po.requester else "—"
        return d

    stats = {
        "pending_my_action":   len(pending_db),
        "my_open_pos":         my_open,
        "approved_this_month": approved_month,
        "rejected_this_month": rejected_month,
    }

    return templates.TemplateResponse("dashboard.html", {
        "request":          request,
        "current_user":     user,
        "active_page":      "dashboard",
        "pending_count":    len(pending_db),
        "stats":            stats,
        "recent_pos":       [po_dict(p, with_requester=True) for p in recent_pos_db],
        "pending_approvals":[po_dict(p) for p in pending_db],
    })


# ── PO List ───────────────────────────────────────────────────────────────────

@router.get("/pos", response_class=HTMLResponse)
async def po_list(
    request: Request,
    status: str = "",
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    q = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.requester),
            selectinload(PurchaseOrder.vendor),
            selectinload(PurchaseOrder.site),
        )
        .order_by(desc(PurchaseOrder.created_at))
        .limit(100)
    )

    # Site-based filtering — MD_OWNER sees all, others see only their site
    if user.role == UserRole.REQUESTER:
        q = q.where(PurchaseOrder.requester_id == user.id)
    elif user.role != UserRole.MD_OWNER and user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        if user.site_id:
            q = q.where(PurchaseOrder.site_id == user.site_id)

    if status:
        try:
            q = q.where(PurchaseOrder.status == POStatus(status))
        except ValueError:
            pass

    result = await session.execute(q)
    pos_db = result.scalars().all()

    pos = [{
        "id":            str(p.id),
        "po_number":     p.po_number,
        "status":        p.status.value,
        "priority":      p.priority.value,
        "po_category":   p.po_category,
        "total_amount":  float(p.total_amount),
        "required_by":   p.required_by,
        "created_at":    p.created_at,
        "requester_name":p.requester.full_name if p.requester else "—",
        "requester_id":  str(p.requester_id),
        "vendor_name":   p.vendor.name if p.vendor else "—",
        "site_name":     p.site.name if p.site else None,
    } for p in pos_db]

    return templates.TemplateResponse("po_list.html", {
        "request":       request,
        "current_user":  user,
        "active_page":   "pos",
        "pending_count": 0,
        "pos":           pos,
        "status_filter": status,
    })


# ── New PO form ───────────────────────────────────────────────────────────────

@router.get("/pos/new", response_class=HTMLResponse)
async def new_po_type_select(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    return templates.TemplateResponse("po_type_select.html", {
        "request":       request,
        "current_user":  user,
        "active_page":   "po_new",
        "pending_count": 0,
    })


async def _render_po_type_form(po_type: str, template_name: str, request: Request, session: AsyncSession):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    from datetime import date
    vendors     = (await session.execute(select(Vendor).where(Vendor.is_active == True))).scalars().all()
    departments = (await session.execute(select(Department).where(Department.is_active == True))).scalars().all()
    projects    = (await session.execute(select(Project).where(Project.is_active == True))).scalars().all()


    # Build budget subcategories and remaining for the form — filtered by user's site
    from app.models.models import BudgetCategory as _BC
    _bc_query = select(_BC).where(_BC.is_active == True)
    if user.site_id:
        _bc_query = _bc_query.where(_BC.site_id == user.site_id)
    _budget_cats = (await session.execute(_bc_query)).scalars().all()
    _budget_subcategories = {}
    _budget_remaining = {}
    for _bc in _budget_cats:
        if _bc.category not in _budget_subcategories:
            _budget_subcategories[_bc.category] = []
        if _bc.sub_category and _bc.sub_category not in _budget_subcategories[_bc.category]:
            _budget_subcategories[_bc.category].append(_bc.sub_category)
        _key = f"{_bc.category}::{_bc.sub_category}" if _bc.sub_category else _bc.category
        _rem = float(_bc.budget_amount - _bc.spent_amount)
        _budget_remaining[_key] = _budget_remaining.get(_key, 0) + _rem

    # Build budget subcategories and remaining for the form — filtered by user's site
    from app.models.models import BudgetCategory as _BC
    _bc_query = select(_BC).where(_BC.is_active == True)
    if user.site_id:
        _bc_query = _bc_query.where(_BC.site_id == user.site_id)
    _budget_cats = (await session.execute(_bc_query)).scalars().all()
    _budget_subcategories = {}
    _budget_remaining = {}
    for _bc in _budget_cats:
        if _bc.category not in _budget_subcategories:
            _budget_subcategories[_bc.category] = []
        if _bc.sub_category and _bc.sub_category not in _budget_subcategories[_bc.category]:
            _budget_subcategories[_bc.category].append(_bc.sub_category)
        _key = f"{_bc.category}::{_bc.sub_category}" if _bc.sub_category else _bc.category
        _rem = float(_bc.budget_amount - _bc.spent_amount)
        _budget_remaining[_key] = _budget_remaining.get(_key, 0) + _rem
    from app.services.po_service import PO_TYPE_CLAUSES
    _default_clauses = PO_TYPE_CLAUSES.get(po_type, {})

    # Load all sites for MD/Admin site selector
    _all_sites = (await session.execute(
        select(Site).where(Site.is_active == True).order_by(Site.name)
    )).scalars().all()

    # Build site-aware budget remaining: key = site_id::category::sub_category
    # This lets JS filter by selected site for MD/Admin users
    from app.models.models import BudgetCategory as _BC2
    _all_bc = (await session.execute(
        select(_BC2).where(_BC2.is_active == True)
    )).scalars().all()
    _site_budget_remaining = {}
    for _bc2 in _all_bc:
        _site_key = f"{_bc2.site_id}::{_bc2.category}::{_bc2.sub_category}" \
            if _bc2.sub_category else f"{_bc2.site_id}::{_bc2.category}"
        _rem2 = float(_bc2.budget_amount - _bc2.spent_amount)
        _site_budget_remaining[_site_key] = \
            _site_budget_remaining.get(_site_key, 0) + _rem2

    from app.services.loi_service import LOIService
    _loi_articles = LOIService.fill_articles(po_type, {
        "vendor_name":      "",
        "vendor_contact":   "",
        "po_number":        "DRAFT",
        "total_amount":     0,
        "description":      "",
        "delivery_address": "",
        "required_by":      "",
        "penalty_clauses":  "",
        "delivery_terms":   "",
        "warranty_terms":   "",
        "special_conditions": "",
        "site_name":        "",
    })

    return templates.TemplateResponse(template_name, {
        "request":        request,
        "current_user":   user,
        "active_page":    "po_new",
        "pending_count":  0,
        "po":             None,
        "po_type":        po_type,
        "default_clauses": _default_clauses,
        "loi_articles":   _loi_articles,
        "vendors":        vendors,
        "departments":    departments,
        "projects":       projects,
        "all_sites":      _all_sites,
        "budget_subcategories": _budget_subcategories,
        "budget_remaining": _budget_remaining,
        "site_budget_remaining": _site_budget_remaining,
        "today":          date.today().isoformat(),
        "existing_items": None,
    })


@router.get("/pos/new/service", response_class=HTMLResponse)
async def new_po_service(request: Request, session: AsyncSession = Depends(get_session)):
    return await _render_po_type_form("service", "po_form_service.html", request, session)


@router.get("/pos/new/supply", response_class=HTMLResponse)
async def new_po_supply(request: Request, session: AsyncSession = Depends(get_session)):
    return await _render_po_type_form("supply", "po_form_supply.html", request, session)


@router.get("/pos/new/technology", response_class=HTMLResponse)
async def new_po_technology(request: Request, session: AsyncSession = Depends(get_session)):
    return await _render_po_type_form("technology", "po_form_technology.html", request, session)


# ── PO Detail ─────────────────────────────────────────────────────────────────

@router.get("/pos/{po_id}", response_class=HTMLResponse)
async def po_detail(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    from app.services.po_service import POService
    po = await POService.get_po_detail(session, UUID(po_id))
    if not po:
        raise HTTPException(404, "PO not found")

    # Build site approval chain for display
    from app.models.models import UserRole as _UR
    _site_chain = []
    if po.site_id:
        for _r in [_UR.L1_APPROVER, _UR.L2_APPROVER, _UR.L3_APPROVER, _UR.L4_APPROVER, _UR.FINANCE]:
            _has = (await session.execute(
                select(User).where(User.site_id == po.site_id, User.role == _r, User.is_active == True)
            )).scalars().first()
            if _has:
                _site_chain.append(_r.value)
        _site_chain.append(_UR.MD_OWNER.value)
    else:
        _site_chain = [_UR.L1_APPROVER.value, _UR.MD_OWNER.value]

    # loi-greenlet-fixed
    # Build hidden fields for LOI download forms
    # Access only already-selectinloaded relations to avoid MissingGreenlet
    import json as _json
    from app.services.loi_service import LOIService as _LOI
    _vendor_name = ""
    try:
        if po.vendor:
            _vendor_name = po.vendor.name
    except Exception:
        pass
    _site_name = ""
    try:
        if po.site:
            _site_name = po.site.name
    except Exception:
        pass
    _po_data_for_loi = {
        "vendor_name":        _vendor_name,
        "vendor_contact":     "",
        "po_number":          po.po_number,
        "total_amount":       float(po.total_amount),
        "description":        po.description or "",
        "delivery_address":   po.delivery_address or "",
        "required_by":        po.required_by.strftime("%Y-%m-%d") if po.required_by else "",
        "penalty_clauses":    po.penalty_clauses or "",
        "delivery_terms":     po.delivery_terms or "",
        "warranty_terms":     po.warranty_terms or "",
        "special_conditions": po.special_conditions or "",
        "site_name":          _site_name,
    }
    _po_type = getattr(po, "po_type", None) or "technology"
    _loi_articles = _LOI.fill_articles(_po_type, _po_data_for_loi)
    _articles_json = _json.dumps(_loi_articles)
    _form_data_json = _json.dumps({"total_display": str(float(po.total_amount))})
    _loi_hidden_fields = (
        '<input type="hidden" name="articles_json" value="'
        + _articles_json.replace('"', '&quot;')
        + '"><input type="hidden" name="form_data_json" value="'
        + _form_data_json.replace('"', '&quot;')
        + '">'
    )

    return templates.TemplateResponse("po_detail.html", {
        "request":            request,
        "current_user":       user,
        "active_page":        "pos",
        "pending_count":      0,
        "po":                 po,
        "site_approval_chain": _site_chain,
        "loi_hidden_fields":  _loi_hidden_fields,
    })


# ── Create PO from form submission ────────────────────────────────────────────

# ── LOI Download Routes ───────────────────────────────────────────────────────

@router.post("/pos/loi/download/{po_type}/{fmt}", response_class=HTMLResponse)
async def download_loi(
    po_type: str,
    fmt: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Generate and return a LOI PDF or DOCX file for download."""
    from app.services.loi_service import LOIService
    from fastapi.responses import Response
    import json

    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    form = await request.form()
    try:
        articles_json  = form.get("articles_json", "[]")
        form_data_json = form.get("form_data_json", "{}")
        articles  = json.loads(articles_json)
        form_data = json.loads(form_data_json)
    except Exception:
        articles  = []
        form_data = {}

    # Enrich form_data with vendor name if vendor_id provided
    vendor_name = "[VENDOR NAME]"
    vendor_id = form_data.get("vendor_id", "")
    if vendor_id:
        try:
            _v = (await session.execute(
                select(Vendor).where(Vendor.id == vendor_id)
            )).scalar_one_or_none()
            if _v:
                vendor_name = _v.name
        except Exception:
            pass

    # Enrich with site name if site_id provided
    site_name = "[SITE]"
    site_id_val = form_data.get("site_id", "") or (str(user.site_id) if user.site_id else "")
    if site_id_val:
        try:
            _s = (await session.execute(
                select(Site).where(Site.id == site_id_val)
            )).scalar_one_or_none()
            if _s:
                site_name = _s.name
        except Exception:
            pass

    po_data = {
        "vendor_name":        vendor_name,
        "vendor_contact":     "[CONTACT]",
        "po_number":          "DRAFT",
        "total_amount":       float(form_data.get("total_display", 0) or 0),
        "description":        form_data.get("description", ""),
        "delivery_address":   form_data.get("delivery_address", ""),
        "required_by":        form_data.get("required_by", ""),
        "penalty_clauses":    form_data.get("penalty_clauses", ""),
        "delivery_terms":     form_data.get("delivery_terms", ""),
        "warranty_terms":     form_data.get("warranty_terms", ""),
        "special_conditions": form_data.get("special_conditions", ""),
        "site_name":          site_name,
    }

    # If articles were submitted (edited), use them; otherwise fill fresh
    if not articles:
        articles = LOIService.fill_articles(po_type, po_data)

    try:
        if fmt == "pdf":
            file_bytes   = LOIService.generate_pdf(po_data, articles)
            media_type   = "application/pdf"
            filename     = f"LOI_{po_type.upper()}_DRAFT.pdf"
        elif fmt == "docx":
            file_bytes   = LOIService.generate_docx(po_data, articles)
            media_type   = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            filename     = f"LOI_{po_type.upper()}_DRAFT.docx"
        else:
            return Response("Invalid format", status_code=400)

        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        import traceback
        print("LOI GENERATION ERROR:", traceback.format_exc())
        return Response(f"LOI generation failed: {e}", status_code=500)


@router.post("/pos/service", response_class=HTMLResponse)
async def create_po_service(request: Request, session: AsyncSession = Depends(get_session)):
    return await create_po_submit(request, session)


@router.post("/pos/supply", response_class=HTMLResponse)
async def create_po_supply(request: Request, session: AsyncSession = Depends(get_session)):
    return await create_po_submit(request, session)


@router.post("/pos/technology", response_class=HTMLResponse)
async def create_po_technology(request: Request, session: AsyncSession = Depends(get_session)):
    return await create_po_submit(request, session)


@router.post("/pos", response_class=HTMLResponse)
async def create_po_submit(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    from app.models.models import ApprovalChain
    from app.services.po_service import POService
    from app.schemas.po import POCreate, POLineItemCreate
    from decimal import Decimal
    from datetime import datetime
    import json

    form = await request.form()
    save_action = form.get("save_action", "draft")

    try:
        # Parse line items from hidden JSON field
        line_items_json = form.get("line_items_json", "[]")
        raw_items = json.loads(line_items_json)

        line_items = [
            POLineItemCreate(
                description=item["description"],
                sub_category=item.get("sub_category") or None,
                unit_of_measure=item.get("unit", "nos"),
                quantity=Decimal(str(item.get("qty", 1))),
                unit_rate=Decimal(str(item.get("rate", 0))),
                gst_percent=Decimal(str(item.get("gst", 0))),
            )
            for item in raw_items
            if item.get("description") and float(item.get("rate", 0)) > 0
        ]

        if not line_items:
            raise ValueError("At least one line item with a description and rate is required")

        # Parse required_by date
        required_by_str = form.get("required_by", "")
        required_by = datetime.strptime(required_by_str, "%Y-%m-%d")

        po_data = POCreate(
            vendor_id=form.get("vendor_id"),
            department_id=form.get("department_id") or None,
            project_id=form.get("project_id") or None,
            po_category=form.get("po_category", "material"),
            po_type=form.get("po_type") or None,
            sub_category=None,  # sub_category now lives on each line item
            description=form.get("description", ""),
            delivery_address=form.get("delivery_address", ""),
            required_by=required_by,
            payment_terms=form.get("payment_terms") or None,
            priority=form.get("priority", "normal"),
            line_items=line_items,
            site_id=str(user.site_id) if user.site_id else None,
            penalty_clauses=form.get("penalty_clauses") or None,
            delivery_terms=form.get("delivery_terms") or None,
            warranty_terms=form.get("warranty_terms") or None,
            special_conditions=form.get("special_conditions") or None,
        )

        # Get approval chains
        chains_result = await session.execute(
            select(ApprovalChain).where(ApprovalChain.is_active == True)
        )
        chains = chains_result.scalars().all()

        po = await POService.create_po(session, po_data, user, chains)

        # Save attachments if any
        try:
            import os
            from app.models.models import POAttachment
            from uuid import uuid4 as _uuid4
            att_files = form.getlist("attachments")
            for file in att_files:
                if not hasattr(file, 'filename') or not file.filename:
                    continue
                upload_dir = f"/app/uploads/{po.id}"
                os.makedirs(upload_dir, exist_ok=True)
                ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""
                save_name = f"{str(_uuid4())}.{ext}" if ext else str(_uuid4())
                content_bytes = await file.read()
                with open(f"{upload_dir}/{save_name}", "wb") as f:
                    f.write(content_bytes)
                session.add(POAttachment(
                    id=_uuid4(), purchase_order_id=po.id,
                    filename=file.filename, s3_key=f"{upload_dir}/{save_name}",
                    content_type=file.content_type or "application/octet-stream",
                    size_bytes=len(content_bytes),
                    uploaded_by_id=user.id,
                ))
            await session.commit()
        except Exception as _att_e:
            import logging
            logging.getLogger(__name__).warning("Attachment save failed: %s", _att_e)

        # If submit (not just draft), also submit for approval
        if save_action == "submit":
            po = await POService.submit_po(session, po, user)

        return RedirectResponse(f"/pos/{po.id}", status_code=302)

    except Exception as e:
        # error-handler-fixed-type-specific
        import traceback as _tb
        print("PO CREATE ERROR:", _tb.format_exc())
        from datetime import date
        from app.models.models import BudgetCategory as _BC2
        from app.services.loi_service import LOIService as _LOI
        from app.services.po_service import PO_TYPE_CLAUSES
        try:
            _form2 = await request.form()
            _po_type = _form2.get("po_type") or "service"
        except Exception:
            _po_type = "service"
        _tmap = {
            "service": "po_form_service.html",
            "supply": "po_form_supply.html",
            "technology": "po_form_technology.html",
        }
        _tname = _tmap.get(_po_type, "po_form_service.html")
        vendors = (await session.execute(select(Vendor).where(Vendor.is_active == True))).scalars().all()
        departments = (await session.execute(select(Department).where(Department.is_active == True))).scalars().all()
        projects = (await session.execute(select(Project).where(Project.is_active == True))).scalars().all()
        _loi_arts = _LOI.fill_articles(_po_type, {
            "vendor_name": "", "vendor_contact": "", "po_number": "DRAFT",
            "total_amount": 0, "description": "", "delivery_address": "",
            "required_by": "", "penalty_clauses": "", "delivery_terms": "",
            "warranty_terms": "", "special_conditions": "", "site_name": "",
        })
        return templates.TemplateResponse(_tname, {
            "request": request, "current_user": user, "active_page": "po_new",
            "pending_count": 0, "po": None, "po_type": _po_type,
            "vendors": vendors, "departments": departments, "projects": projects,
            "all_sites": [], "budget_subcategories": {}, "budget_remaining": {},
            "site_budget_remaining": {}, "default_clauses": PO_TYPE_CLAUSES.get(_po_type, {}),
            "loi_articles": _loi_arts, "today": date.today().isoformat(),
            "existing_items": None, "error": str(e),
        }, status_code=400)
# ── Submit PO ─────────────────────────────────────────────────────────────────

@router.post("/pos/{po_id}/submit")
async def submit_po(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    from app.services.po_service import POService
    po = await session.get(PurchaseOrder, UUID(po_id))
    if not po:
        raise HTTPException(404, "PO not found")
    try:
        await POService.submit_po(session, po, user)
    except PermissionError as e:
        import traceback
        print("SUBMIT ERROR:", traceback.format_exc())
        err = str(e)
        if "budget" in err.lower():
            return RedirectResponse(f"/pos/{po_id}?error=budget_exceeded", status_code=302)
        return RedirectResponse(f"/pos/{po_id}?error=permission", status_code=302)
    except Exception as e:
        import traceback
        print("SUBMIT ERROR:", traceback.format_exc())
    return RedirectResponse(f"/pos/{po_id}", status_code=302)


@router.post("/pos/{po_id}/approve")
async def approve_po(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    form = await request.form()
    comments = form.get("comments", "")
    from app.services.po_service import POService
    po = await session.get(PurchaseOrder, UUID(po_id))
    if not po:
        raise HTTPException(404, "PO not found")
    try:
        from app.schemas.po import POApproveRequest
        from app.models.models import ApprovalAction
        req = POApproveRequest(action=ApprovalAction.APPROVE, comments=comments or None)
        await POService.process_approval(session, po, user, req)
    except Exception as e:
        import traceback
        print("APPROVE ERROR:", traceback.format_exc())
    return RedirectResponse(f"/pos/{po_id}", status_code=302)


@router.post("/pos/{po_id}/reject")
async def reject_po(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    form = await request.form()
    reason = form.get("reason", "")
    from app.services.po_service import POService
    po = await session.get(PurchaseOrder, UUID(po_id))
    if not po:
        raise HTTPException(404, "PO not found")
    try:
        from app.schemas.po import POApproveRequest
        from app.models.models import ApprovalAction
        req = POApproveRequest(action=ApprovalAction.REJECT, comments=reason or None)
        await POService.process_approval(session, po, user, req)
    except Exception as e:
        import traceback
        print("REJECT ERROR:", traceback.format_exc())
    return RedirectResponse(f"/pos/{po_id}", status_code=302)


@router.post("/pos/{po_id}/return")
async def return_po(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    form = await request.form()
    reason = form.get("reason", "")
    from app.services.po_service import POService
    po = await session.get(PurchaseOrder, UUID(po_id))
    if not po:
        raise HTTPException(404, "PO not found")
    try:
        from app.schemas.po import POApproveRequest
        from app.models.models import ApprovalAction
        req = POApproveRequest(action=ApprovalAction.RETURN, comments=reason or None)
        await POService.process_approval(session, po, user, req)
    except Exception as e:
        import traceback
        print("RETURN ERROR:", traceback.format_exc())
    return RedirectResponse(f"/pos/{po_id}", status_code=302)


@router.get("/approvals", response_class=HTMLResponse)
async def approvals_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    pending_statuses = {
        UserRole.L1_APPROVER: [POStatus.SUBMITTED],
        UserRole.L2_APPROVER: [POStatus.L1_APPROVED],
        UserRole.L3_APPROVER: [POStatus.L2_APPROVED],
        UserRole.L4_APPROVER: [POStatus.L3_APPROVED],
        UserRole.ADMIN:       [POStatus.SUBMITTED, POStatus.L1_APPROVED, POStatus.L2_APPROVED, POStatus.L3_APPROVED],
        UserRole.FINANCE:     [POStatus.L4_APPROVED],
    }.get(user.role, [])
    if pending_statuses:
        apq = (select(PurchaseOrder).options(selectinload(PurchaseOrder.requester),selectinload(PurchaseOrder.vendor),selectinload(PurchaseOrder.department),selectinload(PurchaseOrder.site)).where(PurchaseOrder.status.in_(pending_statuses)).order_by(desc(PurchaseOrder.created_at)))
        if user.role not in [UserRole.ADMIN, UserRole.MD_OWNER] and user.site_id:
            apq = apq.where(PurchaseOrder.site_id == user.site_id)
        result = await session.execute(apq)
        pos_db = result.scalars().all()
    else:
        pos_db = []
    pos = [{
        "id": str(p.id), "po_number": p.po_number, "status": p.status.value,
        "priority": p.priority.value, "po_category": p.po_category,
        "total_amount": float(p.total_amount), "required_by": p.required_by,
        "submitted_at": p.submitted_at, "requester_name": p.requester.full_name if p.requester else "—",
        "vendor_name": p.vendor.name if p.vendor else "—",
        "department_name": p.department.name if p.department else "—",
        "current_level": p.current_level, "required_levels": p.required_levels,
        "site_name": p.site.name if p.site else None,
    } for p in pos_db]
    return templates.TemplateResponse("approvals.html", {
        "request": request, "current_user": user, "active_page": "approvals",
        "pending_count": len(pos), "pos": pos,
    })


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role.value not in ["admin", "ADMIN", "md_owner", "MD_OWNER"]:
        return to_login()
    result = await session.execute(select(User).options(selectinload(User.department)).where(User.is_active == True).order_by(User.full_name))
    users_db = result.scalars().all()
    departments = (await session.execute(select(Department).where(Department.is_active == True))).scalars().all()
    from app.models.models import Site as _Site
    _sites = (await session.execute(select(_Site).order_by(_Site.code))).scalars().all()
    _smap = {s.id: s for s in _sites}
    users = [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role.value,
              "is_active": u.is_active, "department": u.department.name if u.department else "—",
              "site_name": _smap[u.site_id].name if u.site_id and u.site_id in _smap else None,
              "site_code": _smap[u.site_id].code if u.site_id and u.site_id in _smap else None,
              } for u in users_db]
    sites = [{"id": str(s.id), "name": s.name, "code": s.code} for s in _sites]
    return templates.TemplateResponse("admin_users.html", {
        "request": request, "current_user": user, "active_page": "admin_users",
        "pending_count": 0, "users": users, "departments": departments,
        "roles": [r.value for r in UserRole], "sites": sites,
    })


@router.post("/admin/users/create")
async def admin_create_user(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()
    from passlib.context import CryptContext
    from uuid import uuid4
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    form = await request.form()
    try:
        new_user = User(
            id=uuid4(), email=form.get("email"), full_name=form.get("full_name"),
            hashed_password=pwd_context.hash(form.get("password")),
            role=UserRole(form.get("role")),
            department_id=UUID(form.get("department_id")) if form.get("department_id") else None,
            is_active=True,
        )
        session.add(new_user)
        await session.commit()
    except Exception as e:
        import traceback
        print("CREATE USER ERROR:", traceback.format_exc())
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/admin/users/{user_id}/toggle")
async def admin_toggle_user(user_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    current = await get_user_from_cookie(request, session)
    if not current or current.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()
    u = await session.get(User, UUID(user_id))
    if u:
        u.is_active = not u.is_active
        await session.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.get("/admin/chains", response_class=HTMLResponse)
async def admin_chains(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()
    from app.models.models import ApprovalChain
    result = await session.execute(select(ApprovalChain).order_by(ApprovalChain.po_category, ApprovalChain.min_amount))
    chains_db = result.scalars().all()
    chains = [{"id": str(c.id), "name": c.name, "po_category": c.po_category,
               "min_amount": float(c.min_amount), "max_amount": float(c.max_amount) if c.max_amount else None,
               "required_levels": c.required_levels, "sla_hours": c.sla_hours, "is_active": c.is_active} for c in chains_db]
    return templates.TemplateResponse("admin_chains.html", {
        "request": request, "current_user": user, "active_page": "admin_chains",
        "pending_count": 0, "chains": chains,
        "categories": ['material','subcontractor','equipment_rental','office_admin','it_software','capital_expenditure','urgent_emergency'],
    })


@router.post("/admin/chains/create")
async def admin_create_chain(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()
    from app.models.models import ApprovalChain
    from decimal import Decimal
    from uuid import uuid4
    form = await request.form()
    try:
        chain = ApprovalChain(
            id=uuid4(), name=form.get("name"), po_category=form.get("po_category"),
            min_amount=Decimal(form.get("min_amount", "0")),
            max_amount=Decimal(form.get("max_amount")) if form.get("max_amount") else None,
            required_levels=int(form.get("required_levels", 2)),
            sla_hours=int(form.get("sla_hours", 24)), is_active=True,
        )
        session.add(chain)
        await session.commit()
    except Exception as e:
        import traceback
        print("CREATE CHAIN ERROR:", traceback.format_exc())
    return RedirectResponse("/admin/chains", status_code=302)


# ── Edit PO form ──────────────────────────────────────────────────────────────

@router.get("/pos/{po_id}/edit", response_class=HTMLResponse)
async def edit_po_form(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    from datetime import date
    from app.services.po_service import POService
    po = await POService.get_po_detail(session, UUID(po_id))
    if not po:
        raise HTTPException(404, "PO not found")

    if po.status != POStatus.DRAFT:
        return RedirectResponse(f"/pos/{po_id}", status_code=302)

    vendors     = (await session.execute(select(Vendor).where(Vendor.is_active == True))).scalars().all()
    departments = (await session.execute(select(Department).where(Department.is_active == True))).scalars().all()
    projects    = (await session.execute(select(Project).where(Project.is_active == True))).scalars().all()

    existing_items = [
        {"description": item.description, "unit": item.unit_of_measure,
         "qty": float(item.quantity), "rate": float(item.unit_rate),
         "gst": float(item.gst_percent), "total": float(item.total)}
        for item in po.line_items
    ]


    # Build budget subcategories and remaining for the form — filtered by user's site
    from app.models.models import BudgetCategory as _BC
    _bc_query = select(_BC).where(_BC.is_active == True)
    if user.site_id:
        _bc_query = _bc_query.where(_BC.site_id == user.site_id)
    _budget_cats = (await session.execute(_bc_query)).scalars().all()
    _budget_subcategories = {}
    _budget_remaining = {}
    for _bc in _budget_cats:
        if _bc.category not in _budget_subcategories:
            _budget_subcategories[_bc.category] = []
        if _bc.sub_category and _bc.sub_category not in _budget_subcategories[_bc.category]:
            _budget_subcategories[_bc.category].append(_bc.sub_category)
        _key = f"{_bc.category}::{_bc.sub_category}" if _bc.sub_category else _bc.category
        _rem = float(_bc.budget_amount - _bc.spent_amount)
        _budget_remaining[_key] = _budget_remaining.get(_key, 0) + _rem
    return templates.TemplateResponse("po_form.html", {
        "request":        request,
        "current_user":   user,
        "active_page":    "pos",
        "pending_count":  0,
        "po":             po,
        "vendors":        vendors,
        "departments":    departments,
        "projects":       projects,
        "budget_subcategories": _budget_subcategories,
        "budget_remaining": _budget_remaining,
        "today":          date.today().isoformat(),
        "existing_items": existing_items,
    })


@router.post("/pos/{po_id}/edit")
async def edit_po_submit(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    from app.services.po_service import POService
    from app.schemas.po import POCreate, POLineItemCreate
    from decimal import Decimal
    from datetime import datetime
    import json

    po = await session.get(PurchaseOrder, UUID(po_id))
    if not po or po.status != POStatus.DRAFT:
        return RedirectResponse(f"/pos/{po_id}", status_code=302)

    form = await request.form()
    save_action = form.get("save_action", "draft")

    try:
        line_items_json = form.get("line_items_json", "[]")
        raw_items = json.loads(line_items_json)
        line_items = [
            POLineItemCreate(
                description=item["description"],
                sub_category=item.get("sub_category") or None,
                unit_of_measure=item.get("unit", "nos"),
                quantity=Decimal(str(item.get("qty", 1))),
                unit_rate=Decimal(str(item.get("rate", 0))),
                gst_percent=Decimal(str(item.get("gst", 0))),
            )
            for item in raw_items
            if item.get("description") and float(item.get("rate", 0)) > 0
        ]

        if not line_items:
            raise ValueError("At least one line item with a description and rate is required")

        required_by_str = form.get("required_by", "")
        required_by = datetime.strptime(required_by_str, "%Y-%m-%d")

        # Update PO fields
        po.vendor_id = UUID(form.get("vendor_id"))
        po.department_id = UUID(form.get("department_id")) if form.get("department_id") else None
        po.project_id = UUID(form.get("project_id")) if form.get("project_id") else None
        po.po_category = form.get("po_category", "material")
        po.description = form.get("description", "")
        po.delivery_address = form.get("delivery_address", "")
        po.required_by = required_by
        po.payment_terms = form.get("payment_terms") or None
        po.priority = form.get("priority", "normal")

        # Delete old line items and recreate
        from app.models.models import POLineItem
        from sqlalchemy import delete
        await session.execute(delete(POLineItem).where(POLineItem.purchase_order_id == po.id))

        subtotal = Decimal(0)
        gst_total = Decimal(0)
        for i, item in enumerate(line_items):
            amount = item.quantity * item.unit_rate
            gst_amount = amount * item.gst_percent / 100
            total = amount + gst_amount
            subtotal += amount
            gst_total += gst_amount
            li = POLineItem(
                purchase_order_id=po.id,
                sort_order=i,
                description=item.description,
                unit_of_measure=item.unit_of_measure,
                quantity=item.quantity,
                unit_rate=item.unit_rate,
                amount=amount,
                gst_percent=item.gst_percent,
                gst_amount=gst_amount,
                total=total,
            )
            session.add(li)

        po.subtotal = subtotal
        po.gst_amount = gst_total
        po.total_amount = subtotal + gst_total

        # Recalculate approval levels based on new amount
        from app.models.models import ApprovalChain
        from app.services.approval_engine import ApprovalEngine
        chains_result = await session.execute(select(ApprovalChain).where(ApprovalChain.is_active == True))
        chains = chains_result.scalars().all()
        po.required_levels = ApprovalEngine.resolve_required_levels(po.po_category, po.total_amount, chains)

        await session.commit()

        if save_action == "submit":
            from app.models.models import ApprovalChain
            chains_result = await session.execute(select(ApprovalChain).where(ApprovalChain.is_active == True))
            chains = chains_result.scalars().all()
            await POService.submit_po(session, po, user)

        return RedirectResponse(f"/pos/{po_id}", status_code=302)

    except Exception as e:
        import traceback
        print("EDIT PO ERROR:", traceback.format_exc())
        return RedirectResponse(f"/pos/{po_id}/edit", status_code=302)


# ── PDF Download ──────────────────────────────────────────────────────────────



@router.post("/pos/{po_id}/authorize-budget")
async def authorize_budget(po_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """MD authorizes extra budget spending for a PO."""
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    if user.role.value not in ['md_owner', 'MD_OWNER', 'admin', 'ADMIN']:
        return RedirectResponse(f"/pos/{po_id}", status_code=302)

    po = await session.get(PurchaseOrder, UUID(po_id))
    if not po:
        raise HTTPException(404, "PO not found")

    from datetime import datetime as _dt
    po.budget_authorized = True
    po.budget_authorized_at = _dt.utcnow()
    await session.commit()

    # Notify requester
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        from app.core.config import settings as _settings
        _url = _settings.REDIS_URL.replace("redis://", "")
        _host, _port = _url.split(":") if ":" in _url else (_url, "6379")
        redis = await create_pool(RedisSettings(host=_host, port=int(_port)))
        await redis.enqueue_job("send_budget_authorized_email", str(po.id))
        await redis.aclose()
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning("Budget authorized email failed: %s", _e)

    return RedirectResponse(f"/pos/{po_id}", status_code=302)

# unified-po-loi-download
@router.get("/pos/{po_id}/pdf")
async def download_po_pdf(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Unified PO + LOI document download as PDF."""
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    from fastapi.responses import Response
    from app.services.po_service import POService
    from app.services.loi_service import LOIService
    from app.models.models import ApprovalStep as _AS, Site as _Site
    from sqlalchemy.orm import selectinload as _sli

    result = await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == UUID(po_id))
        .options(
            _sli(PurchaseOrder.vendor), _sli(PurchaseOrder.requester),
            _sli(PurchaseOrder.line_items),
            _sli(PurchaseOrder.approval_steps).selectinload(_AS.approver),
            _sli(PurchaseOrder.department), _sli(PurchaseOrder.project),
            _sli(PurchaseOrder.site),
        )
    )
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(404, "PO not found")

    po_data = _build_po_data(po)
    po_type = getattr(po, "po_type", None) or "technology"
    articles = LOIService.fill_articles(po_type, po_data)

    try:
        pdf_bytes = _generate_unified_pdf(po, po_data, articles)
    except Exception as e:
        import traceback
        print("PDF ERROR:", traceback.format_exc())
        raise HTTPException(500, f"PDF generation failed: {e}")

    filename = f"{po.po_number}_LOI.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/pos/{po_id}/docx")
async def download_po_docx(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Unified PO + LOI document download as Word DOCX."""
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()
    from fastapi.responses import Response
    from app.services.loi_service import LOIService
    from app.models.models import ApprovalStep as _AS
    from sqlalchemy.orm import selectinload as _sli

    result = await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == UUID(po_id))
        .options(
            _sli(PurchaseOrder.vendor), _sli(PurchaseOrder.requester),
            _sli(PurchaseOrder.line_items),
            _sli(PurchaseOrder.approval_steps).selectinload(_AS.approver),
            _sli(PurchaseOrder.department), _sli(PurchaseOrder.project),
            _sli(PurchaseOrder.site),
        )
    )
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(404, "PO not found")

    po_data = _build_po_data(po)
    po_type = getattr(po, "po_type", None) or "technology"
    articles = LOIService.fill_articles(po_type, po_data)

    try:
        docx_bytes = LOIService.generate_docx(po_data, articles)
    except Exception as e:
        import traceback
        print("DOCX ERROR:", traceback.format_exc())
        raise HTTPException(500, f"DOCX generation failed: {e}")

    filename = f"{po.po_number}_LOI.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_po_data(po) -> dict:
    """Build the po_data dict for LOI template filling from a loaded PO object."""
    return {
        "vendor_name":        po.vendor.name if po.vendor else "[VENDOR NAME]",
        "vendor_contact":     po.vendor.email or "" if po.vendor else "",
        "po_number":          po.po_number,
        "total_amount":       float(po.total_amount),
        "description":        po.description or "",
        "delivery_address":   po.delivery_address or "",
        "required_by":        po.required_by.strftime("%d-%m-%Y") if po.required_by else "",
        "penalty_clauses":    po.penalty_clauses or "",
        "delivery_terms":     po.delivery_terms or "",
        "warranty_terms":     po.warranty_terms or "",
        "special_conditions": po.special_conditions or "",
        "site_name":          po.site.name if po.site else "",
        "subtotal":           float(po.subtotal),
        "gst_amount":         float(po.gst_amount),
        "requester_name":     po.requester.full_name if po.requester else "",
        "po_category":        po.po_category or "",
        "priority":           po.priority.value if po.priority else "normal",
        "payment_terms":      po.payment_terms or "",
        "line_items":         [
            {
                "description":     li.description,
                "sub_category":    getattr(li, "sub_category", "") or "",
                "unit_of_measure": li.unit_of_measure,
                "quantity":        float(li.quantity),
                "unit_rate":       float(li.unit_rate),
                "gst_percent":     float(li.gst_percent),
                "total":           float(li.total),
            }
            for li in (po.line_items or [])
        ],
    }


def _sanitize_pdf_text(text: str) -> str:
    """Replace non-Latin-1 characters with safe ASCII equivalents for fpdf2 Helvetica."""
    if not text:
        return ""
    replacements = {
        "—": "-",   # em dash
        "–": "-",   # en dash
        "‘": "'",   # left single quote
        "’": "'",   # right single quote
        "“": '"',   # left double quote
        "”": '"',   # right double quote
        "₹": "INR ",# rupee sign
        "•": "*",   # bullet
        " ": " ",   # non-breaking space
        "…": "...", # ellipsis
        "·": "*",   # middle dot
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Final safety net: encode to latin-1, replacing anything still outside range
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _generate_unified_pdf(po, po_data: dict, articles: list) -> bytes:
    """
    Generate a unified PDF with:
    1. PEEI header + PO details
    2. Line items table
    3. Terms & Conditions
    4. LOI Articles 1-28
    5. Signature section
    """
    from fpdf import FPDF
    from io import BytesIO

    class PO_PDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 11)
            self.set_fill_color(15, 27, 45)
            self.set_text_color(255, 255, 255)
            self.cell(0, 10, "  PASSAVANT ENERGY & ENVIRONMENT INDIA PVT. LTD.", fill=True, ln=True)
            self.set_text_color(0, 0, 0)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(100, 116, 139)
            self.cell(0, 5, "  PO APPROVAL SYSTEM", ln=True)
            self.set_text_color(0, 0, 0)
            self.ln(2)

        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(150, 150, 150)
            self.cell(0, 5,
                _sanitize_pdf_text(f"{po_data['po_number']} | Page {self.page_no()} | Confidential"),
                align="C")
            self.set_text_color(0, 0, 0)

        def section_title(self, title):  # encoding-fix2
            self.set_font("Helvetica", "B", 9)
            self.set_fill_color(248, 250, 252)
            self.set_draw_color(226, 232, 240)
            self.cell(0, 7, "  " + _sanitize_pdf_text(str(title)), border="B", fill=True, ln=True)
            self.ln(2)

        def field_row(self, label, value, w1=45, w2=85):
            self.set_font("Helvetica", "", 8)
            self.set_text_color(100, 116, 139)
            self.cell(w1, 5, _sanitize_pdf_text(str(label)))
            self.set_text_color(0, 0, 0)
            self.set_font("Helvetica", "B", 8)
            self.cell(w2, 5, _sanitize_pdf_text(str(value))[:60], ln=True)
            self.set_font("Helvetica", "", 9)

    pdf = PO_PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 20, 15)
    pdf.add_page()

    # ── PO Header Info ────────────────────────────────────────────────────────
    pdf.section_title("PURCHASE ORDER DETAILS")

    pdf.field_row("PO Number:", po_data["po_number"])
    pdf.field_row("Vendor:", po_data["vendor_name"])
    pdf.field_row("Site:", po_data["site_name"])
    pdf.field_row("Category:", po_data["po_category"].replace("_", " ").title())
    pdf.field_row("Priority:", po_data["priority"].title())
    pdf.field_row("Required By:", po_data["required_by"])
    pdf.field_row("Payment Terms:", po_data["payment_terms"])
    pdf.field_row("Requester:", po_data["requester_name"])
    pdf.field_row("Delivery Address:", po_data["delivery_address"][:80])
    pdf.ln(2)

    # Description
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(45, 5, "Description:")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 8)
    desc = po_data["description"]
    pdf.multi_cell(0, 5, _sanitize_pdf_text(desc[:300] + ("..." if len(desc) > 300 else "")))
    pdf.ln(3)

    # ── Line Items ────────────────────────────────────────────────────────────
    pdf.section_title("LINE ITEMS")
    col_widths = [60, 30, 15, 20, 20, 15, 20]
    headers = ["Description", "Sub-Category", "Unit", "Qty", "Rate (INR)", "GST%", "Total (INR)"]

    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(248, 250, 252)
    for i, h in enumerate(headers):
        align = "R" if i >= 3 else "L"
        pdf.cell(col_widths[i], 6, h, border=1, fill=True, align=align)
    pdf.ln()

    pdf.set_font("Helvetica", "", 7)
    for item in po_data["line_items"]:
        pdf.cell(col_widths[0], 5, _sanitize_pdf_text(item["description"][:35]), border="B")
        pdf.cell(col_widths[1], 5, (item["sub_category"] or "")[:18], border="B")
        pdf.cell(col_widths[2], 5, item["unit_of_measure"], border="B", align="C")
        pdf.cell(col_widths[3], 5, f"{item['quantity']:.2f}", border="B", align="R")
        pdf.cell(col_widths[4], 5, f"{item['unit_rate']:,.2f}", border="B", align="R")
        pdf.cell(col_widths[5], 5, f"{item['gst_percent']:.0f}%", border="B", align="R")
        pdf.cell(col_widths[6], 5, f"{item['total']:,.2f}", border="B", align="R")
        pdf.ln()

    # Totals
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(sum(col_widths[:6]), 6, "Subtotal", border="T", align="R")
    pdf.cell(col_widths[6], 6, f"INR {po_data['subtotal']:,.2f}", border="T", align="R")
    pdf.ln()
    pdf.cell(sum(col_widths[:6]), 6, "GST", align="R")
    pdf.cell(col_widths[6], 6, f"INR {po_data['gst_amount']:,.2f}", align="R")
    pdf.ln()
    pdf.set_fill_color(239, 246, 255)
    pdf.set_text_color(37, 99, 235)
    pdf.cell(sum(col_widths[:6]), 7, "GRAND TOTAL", fill=True, align="R")
    pdf.cell(col_widths[6], 7, f"INR {po_data['total_amount']:,.2f}", fill=True, align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    # ── Terms & Conditions ────────────────────────────────────────────────────
    if any([po_data["penalty_clauses"], po_data["delivery_terms"],
            po_data["warranty_terms"], po_data["special_conditions"]]):
        pdf.section_title("TERMS & CONDITIONS")
        tnc_fields = [
            ("Penalty Clauses", po_data["penalty_clauses"]),
            ("Delivery Terms", po_data["delivery_terms"]),
            ("Warranty Terms", po_data["warranty_terms"]),
            ("Special Conditions", po_data["special_conditions"]),
        ]
        for label, val in tnc_fields:
            if val:
                pdf.set_font("Helvetica", "B", 8)
                pdf.cell(0, 5, label + ":", ln=True)
                pdf.set_font("Helvetica", "", 8)
                pdf.multi_cell(0, 4, _sanitize_pdf_text(val[:500]))
                pdf.ln(2)

    # ── LOI Articles ──────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("LETTER OF INTENT — TERMS AND CONDITIONS")
    pdf.ln(2)

    # Intro
    pdf.set_font("Helvetica", "", 9)
    intro = _sanitize_pdf_text(
        f"Passavant Energy & Environment India Pvt. Ltd. (PEEIPL) is pleased to issue "
        f"this Letter of Intent to M/s {po_data['vendor_name']} subject to the following "
        f"terms and conditions."
    )
    pdf.multi_cell(0, 5, _sanitize_pdf_text(intro))
    pdf.ln(4)

    for article in articles:
        pdf.set_font("Helvetica", "B", 9)
        heading = f"ARTICLE {article['number']} - {article['title']}"
        pdf.multi_cell(0, 5, _sanitize_pdf_text(heading))
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 8)
        body = _sanitize_pdf_text(article.get("body", ""))
        pdf.multi_cell(0, 4, body)
        pdf.ln(4)

    # ── Signatures ────────────────────────────────────────────────────────────
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5,
        "Please sign and return a copy of this LOI as acceptance of the above terms.",
        ln=True)
    pdf.ln(10)

    col = (pdf.w - pdf.l_margin - pdf.r_margin) / 2
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(col, 5, _sanitize_pdf_text("For Passavant Energy & Environment India Pvt. Ltd."))
    pdf.cell(col, 5, _sanitize_pdf_text(f"For {po_data['vendor_name']}"), ln=True)
    pdf.ln(16)
    x = pdf.l_margin
    pdf.line(x, pdf.get_y(), x + col - 5, pdf.get_y())
    pdf.line(x + col + 5, pdf.get_y(), x + col * 2, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(col, 5, "Authorised Signatory")
    pdf.cell(col, 5, "Authorised Signatory", ln=True)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()


@router.get("/admin/sites", response_class=HTMLResponse)
async def admin_sites(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()

    from app.models.models import Site, BudgetCategory, UserRole as UR
    from sqlalchemy import func

    result = await session.execute(select(Site).order_by(Site.name))
    sites_db = result.scalars().all()

    sites = []
    for s in sites_db:
        # Total budget
        budget_result = await session.execute(
            select(func.sum(BudgetCategory.budget_amount))
            .where(BudgetCategory.site_id == s.id, BudgetCategory.is_active == True)
        )
        total_budget = float(budget_result.scalar_one() or 0)

        # Total spent
        spent_result = await session.execute(
            select(func.sum(BudgetCategory.spent_amount))
            .where(BudgetCategory.site_id == s.id, BudgetCategory.is_active == True)
        )
        total_spent = float(spent_result.scalar_one() or 0)

        # User count
        user_count_result = await session.execute(
            select(func.count(User.id)).where(User.site_id == s.id, User.is_active == True)
        )
        user_count = user_count_result.scalar_one() or 0

        # PO count
        po_count_result = await session.execute(
            select(func.count(PurchaseOrder.id)).where(
                PurchaseOrder.site_id == s.id,
                PurchaseOrder.status.not_in([POStatus.APPROVED, POStatus.REJECTED, POStatus.CANCELLED, POStatus.CLOSED])
            )
        )
        po_count = po_count_result.scalar_one() or 0

        sites.append({
            "id": str(s.id), "name": s.name, "code": s.code,
            "location": s.location, "is_active": s.is_active,
            "total_budget": total_budget, "total_spent": total_spent,
            "user_count": user_count, "po_count": po_count,
        })

    return templates.TemplateResponse("admin_sites.html", {
        "request": request, "current_user": user,
        "active_page": "admin_sites", "pending_count": 0, "sites": sites,
    })


@router.post("/admin/sites/create")
async def admin_create_site(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()

    from app.models.models import Site, BudgetCategory
    from datetime import datetime
    from uuid import uuid4
    from decimal import Decimal

    form = await request.form()
    try:
        site = Site(
            id=uuid4(), name=form.get("name"), code=form.get("code").upper(),
            location=form.get("location") or None, is_active=True,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        session.add(site)
        await session.flush()

        # Create default budget categories
        DEFAULTS = [
            ("material","Steel",500000),("material","Cement",300000),("material","Sand",200000),
            ("subcontractor","Civil Work",800000),("subcontractor","Electrical Work",400000),
            ("equipment_rental","Crane",250000),("office_admin","Stationery",50000),
            ("urgent_emergency","Emergency Repairs",300000),
        ]
        for cat, subcat, budget in DEFAULTS:
            session.add(BudgetCategory(
                id=uuid4(), site_id=site.id, category=cat, sub_category=subcat,
                budget_amount=Decimal(str(budget)), spent_amount=Decimal(0),
                is_active=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ))

        await session.commit()
    except Exception as e:
        import traceback; print("CREATE SITE ERROR:", traceback.format_exc())

    return RedirectResponse("/admin/sites", status_code=302)


@router.get("/admin/sites/{site_id}/budget", response_class=HTMLResponse)
async def admin_site_budget(site_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()

    from app.models.models import Site, BudgetCategory
    from sqlalchemy import func

    site = await session.get(Site, UUID(site_id))
    if not site:
        raise HTTPException(404, "Site not found")

    budgets_db = (await session.execute(
        select(BudgetCategory).where(BudgetCategory.site_id == UUID(site_id))
        .order_by(BudgetCategory.category, BudgetCategory.sub_category)
    )).scalars().all()

    # Group by category
    from collections import defaultdict
    grouped = defaultdict(lambda: {"total_budget": 0, "total_spent": 0, "budget_list": []})
    for b in budgets_db:
        cat = b.category
        grouped[cat]["total_budget"] += float(b.budget_amount)
        grouped[cat]["total_spent"] += float(b.spent_amount)
        grouped[cat]["budget_list"].append(b)

    total_budget = sum(v["total_budget"] for v in grouped.values())
    total_spent = sum(v["total_spent"] for v in grouped.values())

    projects = (await session.execute(select(Project).where(Project.is_active == True))).scalars().all()

    categories = ['material','subcontractor','equipment_rental','office_admin',
                  'it_software','capital_expenditure','urgent_emergency']

    return templates.TemplateResponse("admin_site_budget.html", {
        "request": request, "current_user": user,
        "active_page": "admin_sites", "pending_count": 0,
        "site": site, "budgets_by_category": dict(grouped),
        "total_budget": total_budget, "total_spent": total_spent,
        "projects": projects, "categories": categories,
    })


@router.post("/admin/sites/{site_id}/budget/add")
async def admin_add_budget(site_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()

    from app.models.models import BudgetCategory
    from decimal import Decimal
    from datetime import datetime
    from uuid import uuid4

    form = await request.form()
    try:
        session.add(BudgetCategory(
            id=uuid4(), site_id=UUID(site_id),
            project_id=UUID(form.get("project_id")) if form.get("project_id") else None,
            category=form.get("category"),
            sub_category=None,  # sub_category now lives on each line item
            budget_amount=Decimal(form.get("budget_amount")),
            spent_amount=Decimal(0), is_active=True,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        ))
        await session.commit()
    except Exception as e:
        import traceback; print("ADD BUDGET ERROR:", traceback.format_exc())

    return RedirectResponse(f"/admin/sites/{site_id}/budget", status_code=302)


@router.post("/admin/sites/{site_id}/budget/edit")
async def admin_edit_budget(site_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()

    from app.models.models import BudgetCategory
    from decimal import Decimal

    form = await request.form()
    try:
        b = await session.get(BudgetCategory, UUID(form.get("budget_id")))
        if b:
            b.budget_amount = Decimal(form.get("budget_amount"))
            await session.commit()
    except Exception as e:
        import traceback; print("EDIT BUDGET ERROR:", traceback.format_exc())

    return RedirectResponse(f"/admin/sites/{site_id}/budget", status_code=302)


@router.get("/admin/sites/{site_id}/users", response_class=HTMLResponse)
async def admin_site_users(site_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()

    from app.models.models import Site

    site = await session.get(Site, UUID(site_id))
    if not site:
        raise HTTPException(404, "Site not found")

    users_db = (await session.execute(
        select(User).where(User.site_id == UUID(site_id)).order_by(User.full_name)
    )).scalars().all()

    users = [{"id": str(u.id), "email": u.email, "full_name": u.full_name,
              "role": u.role.value, "is_active": u.is_active} for u in users_db]

    roles = ["requester","l1_approver","l2_approver","l3_approver","l4_approver"]

    return templates.TemplateResponse("admin_site_users.html", {
        "request": request, "current_user": user,
        "active_page": "admin_sites", "pending_count": 0,
        "site": site, "users": users, "roles": roles,
    })


@router.post("/admin/sites/{site_id}/users/create")
async def admin_site_create_user(site_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user or user.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()

    from passlib.context import CryptContext
    from uuid import uuid4
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    form = await request.form()

    try:
        new_user = User(
            id=uuid4(), email=form.get("email"), full_name=form.get("full_name"),
            hashed_password=pwd.hash(form.get("password")),
            role=UserRole(form.get("role")),
            site_id=UUID(site_id), is_active=True,
        )
        session.add(new_user)
        await session.commit()
    except Exception as e:
        import traceback; print("CREATE SITE USER ERROR:", traceback.format_exc())

    return RedirectResponse(f"/admin/sites/{site_id}/users", status_code=302)


@router.post("/admin/users/{user_id}/change-role")
async def admin_change_role(user_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    current = await get_user_from_cookie(request, session)
    if not current or current.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()
    form = await request.form()
    u = await session.get(User, UUID(user_id))
    if u:
        u.role = UserRole(form.get("role"))
        await session.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/admin/users/{user_id}/change-site")
async def admin_change_site(user_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    current = await get_user_from_cookie(request, session)
    if not current or current.role not in [UserRole.ADMIN, UserRole.MD_OWNER]:
        return to_login()
    form = await request.form()
    u = await session.get(User, UUID(user_id))
    if u:
        site_id = form.get("site_id")
        u.site_id = UUID(site_id) if site_id else None
        await session.commit()
        print(f"Site changed: {u.full_name} -> {site_id}")
    return RedirectResponse("/admin/users", status_code=302)



# ── File Upload ───────────────────────────────────────────────────────────────

@router.post("/pos/{po_id}/attachments")
async def upload_attachment(
    po_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    import os, shutil
    from fastapi import UploadFile
    from app.models.models import POAttachment
    from uuid import uuid4

    upload_dir = f"/app/uploads/{po_id}"
    os.makedirs(upload_dir, exist_ok=True)

    form = await request.form()
    files = form.getlist("attachments")

    for file in files:
        if not hasattr(file, 'filename') or not file.filename:
            continue
        file_id = str(uuid4())
        ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""
        save_name = f"{file_id}.{ext}" if ext else file_id
        save_path = f"{upload_dir}/{save_name}"

        with open(save_path, "wb") as f:
            content_bytes = await file.read()
            f.write(content_bytes)

        att = POAttachment(
            id=uuid4(),
            purchase_order_id=UUID(po_id),
            filename=file.filename,
            s3_key=save_path,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(content_bytes),
        )
        session.add(att)

    await session.commit()
    return RedirectResponse(f"/pos/{po_id}", status_code=302)


@router.get("/pos/{po_id}/attachments/{att_id}")
async def download_attachment(
    po_id: str,
    att_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    from app.models.models import POAttachment
    from fastapi.responses import FileResponse
    import os

    att = await session.get(POAttachment, UUID(att_id))
    if not att or str(att.purchase_order_id) != po_id:
        raise HTTPException(404, "Attachment not found")

    if not os.path.exists(att.s3_key):
        raise HTTPException(404, "File not found on disk")

    return FileResponse(
        path=att.s3_key,
        filename=att.filename,
        media_type=att.content_type,
    )

# ── Analytics / Reports ───────────────────────────────────────────────────────

@router.get("/reports", response_class=HTMLResponse)
async def analytics_page(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_user_from_cookie(request, session)
    if not user:
        return to_login()

    from sqlalchemy import func, case
    from app.models.models import Site
    from datetime import datetime, timedelta
    from calendar import month_abbr

    now = datetime.utcnow()

    # Base query filter based on role/site
    def site_filter(q):
        if user.role in [UserRole.ADMIN, UserRole.MD_OWNER]:
            return q
        if user.role == UserRole.REQUESTER:
            return q.where(PurchaseOrder.requester_id == user.id)
        if user.site_id:
            return q.where(PurchaseOrder.site_id == user.site_id)
        return q

    # ── Summary stats ─────────────────────────────────────────────────────────
    total = (await session.execute(site_filter(select(func.count(PurchaseOrder.id))))).scalar_one() or 0
    approved = (await session.execute(site_filter(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == "approved")))).scalar_one() or 0
    approved_value = (await session.execute(site_filter(select(func.coalesce(func.sum(PurchaseOrder.total_amount), 0)).where(PurchaseOrder.status == "approved")))).scalar_one() or 0
    rejected = (await session.execute(site_filter(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == "rejected")))).scalar_one() or 0
    rejected_month = (await session.execute(site_filter(select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.status == "rejected",
        func.extract("month", PurchaseOrder.rejected_at) == now.month,
        func.extract("year", PurchaseOrder.rejected_at) == now.year,
    )))).scalar_one() or 0
    in_progress = (await session.execute(site_filter(select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.status.in_(["submitted", "l1_approved", "l2_approved", "l3_approved", "l4_approved", "l5_approved"])
    )))).scalar_one() or 0

    stats = {
        "total": total, "approved": approved, "approved_value": float(approved_value),
        "rejected": rejected, "rejected_month": rejected_month, "in_progress": in_progress,
    }

    # ── Status breakdown ──────────────────────────────────────────────────────
    status_counts = {}
    for s in POStatus:
        cnt = (await session.execute(site_filter(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == s)))).scalar_one() or 0
        if cnt > 0:
            status_counts[s.value] = cnt

    status_breakdown = [
        {"status": k, "count": v, "pct": round((v / total * 100) if total > 0 else 0)}
        for k, v in sorted(status_counts.items(), key=lambda x: -x[1])
    ]

    # ── Category spending ─────────────────────────────────────────────────────
    cats = ['material','subcontractor','equipment_rental','office_admin','it_software','capital_expenditure','urgent_emergency']
    category_spending = []
    for cat in cats:
        q = site_filter(select(
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(PurchaseOrder.total_amount), 0)
        ).where(PurchaseOrder.po_category == cat))
        cnt, total_val = (await session.execute(q)).one()
        if cnt > 0:
            category_spending.append({"category": cat, "count": cnt, "total": float(total_val)})
    category_spending.sort(key=lambda x: -x["total"])

    # ── Monthly trend (last 6 months) ─────────────────────────────────────────
    monthly_trend = []
    max_count = 1
    for i in range(5, -1, -1):
        d = now - timedelta(days=30 * i)
        cnt = (await session.execute(site_filter(select(func.count(PurchaseOrder.id)).where(
            func.extract("month", PurchaseOrder.created_at) == d.month,
            func.extract("year", PurchaseOrder.created_at) == d.year,
        )))).scalar_one() or 0
        val = (await session.execute(site_filter(select(func.coalesce(func.sum(PurchaseOrder.total_amount), 0)).where(
            func.extract("month", PurchaseOrder.created_at) == d.month,
            func.extract("year", PurchaseOrder.created_at) == d.year,
        )))).scalar_one() or 0
        monthly_trend.append({"label": f"{month_abbr[d.month]} {d.year}", "count": cnt, "value": float(val), "pct": 0})
        if cnt > max_count:
            max_count = cnt
    for m in monthly_trend:
        m["pct"] = round((m["count"] / max_count) * 100) if max_count > 0 else 0

    # ── Site spending ─────────────────────────────────────────────────────────
    sites_db = (await session.execute(select(Site).where(Site.is_active == True))).scalars().all()
    site_spending = []
    for s in sites_db:
        cnt = (await session.execute(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.site_id == s.id))).scalar_one() or 0
        total_val = (await session.execute(select(func.coalesce(func.sum(PurchaseOrder.total_amount), 0)).where(PurchaseOrder.site_id == s.id))).scalar_one() or 0
        approved_val = (await session.execute(select(func.coalesce(func.sum(PurchaseOrder.total_amount), 0)).where(PurchaseOrder.site_id == s.id, PurchaseOrder.status == "approved"))).scalar_one() or 0
        site_spending.append({"code": s.code, "name": s.name, "count": cnt, "total": float(total_val), "approved": float(approved_val)})
    site_spending.sort(key=lambda x: -x["total"])

    # ── Recent approved POs ───────────────────────────────────────────────────
    recent_q = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.vendor), selectinload(PurchaseOrder.requester), selectinload(PurchaseOrder.site))
        .where(PurchaseOrder.status == "approved")
        .order_by(desc(PurchaseOrder.approved_at))
        .limit(10)
    )
    if user.role not in [UserRole.ADMIN, UserRole.MD_OWNER] and user.site_id:
        recent_q = recent_q.where(PurchaseOrder.site_id == user.site_id)
    elif user.role == UserRole.REQUESTER:
        recent_q = recent_q.where(PurchaseOrder.requester_id == user.id)
    recent_pos_db = (await session.execute(recent_q)).scalars().all()
    recent_approved = [{
        "id": str(p.id), "po_number": p.po_number, "po_category": p.po_category,
        "total_amount": float(p.total_amount), "approved_at": p.approved_at,
        "vendor_name": p.vendor.name if p.vendor else "—",
        "requester_name": p.requester.full_name if p.requester else "—",
    } for p in recent_pos_db]

    return templates.TemplateResponse("analytics.html", {
        "request": request, "current_user": user,
        "active_page": "reports", "pending_count": 0,
        "stats": stats, "status_breakdown": status_breakdown,
        "category_spending": category_spending, "monthly_trend": monthly_trend,
        "site_spending": site_spending, "recent_approved": recent_approved,
    })
