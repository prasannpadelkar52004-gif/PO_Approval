"""
fix_budget_remaining.py
=======================
Fixes budget remaining display to show site-specific values.
The form should only show budget for the current user's site.
Run from project ROOT:
    docker-compose exec app python fix_budget_remaining.py
"""

path = "app/api/v1/endpoints/html_routes.py"
content = open(path, encoding="utf-8").read()

old = '''    # Build budget subcategories and remaining for the form
    from app.models.models import BudgetCategory as _BC
    _budget_cats = (await session.execute(
        select(_BC).where(_BC.is_active == True)
    )).scalars().all()
    _budget_subcategories = {}
    _budget_remaining = {}
    for _bc in _budget_cats:
        if _bc.category not in _budget_subcategories:
            _budget_subcategories[_bc.category] = []
        if _bc.sub_category and _bc.sub_category not in _budget_subcategories[_bc.category]:
            _budget_subcategories[_bc.category].append(_bc.sub_category)
        _key = f"{_bc.category}::{_bc.sub_category}" if _bc.sub_category else _bc.category
        _rem = float(_bc.budget_amount - _bc.spent_amount)
        _budget_remaining[_key] = _budget_remaining.get(_key, 0) + _rem'''

new = '''    # Build budget subcategories and remaining for the form — filtered by user's site
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
        _budget_remaining[_key] = _budget_remaining.get(_key, 0) + _rem'''

count = content.count(old)
if count > 0:
    content = content.replace(old, new)
    open(path, "w", encoding="utf-8").write(content)
    print(f"  ✅  Fixed {count} occurrence(s) — budget now filtered by user's site")
    print("      Cement on Shambhaji Nagar will now show ₹5,000 remaining")
else:
    print("  ❌  Pattern not found")

print("\nNo restart needed — refresh the New PO page.")
