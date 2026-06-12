"""
fix_budget_items.py
===================
Renames the 'items' key in the budget grouped dict to 'budget_list'
to avoid conflict with Jinja2/Python dict .items() method.
Run from project ROOT:
    docker-compose exec app python fix_budget_items.py
"""

# Fix 1: html_routes.py — rename 'items' key to 'budget_list'
path = "app/api/v1/endpoints/html_routes.py"
content = open(path, encoding="utf-8").read()

# Show the relevant lines first
print("Searching for grouped dict in html_routes.py...")
for i, line in enumerate(content.splitlines(), 1):
    if "grouped" in line and ("items" in line or "append" in line or "defaultdict" in line):
        print(f"  {i}: {line}")

# Apply replacements
changes = 0
for old, new in [
    ('"items": []', '"budget_list": []'),
    ("'items': []", "'budget_list': []"),
    ('grouped[cat]["items"].append(b)', 'grouped[cat]["budget_list"].append(b)'),
    ("grouped[cat]['items'].append(b)", "grouped[cat]['budget_list'].append(b)"),
]:
    if old in content:
        content = content.replace(old, new)
        print(f"  ✅  Replaced: {old[:50]}")
        changes += 1

if changes:
    open(path, "w", encoding="utf-8").write(content)
    print(f"  ✅  html_routes.py saved ({changes} changes)")
else:
    print("  ❌  No patterns matched in html_routes.py")

# Fix 2: template — use budget_list instead of items
path2 = "app/templates/admin_site_budget.html"
content2 = open(path2, encoding="utf-8").read()

for old, new in [
    ("{% for b in cat_data.items %}", "{% for b in cat_data.budget_list %}"),
    ("{% for b in cat_data.items() %}", "{% for b in cat_data.budget_list %}"),
]:
    if old in content2:
        content2 = content2.replace(old, new)
        print(f"  ✅  Template: replaced '{old}'")

open(path2, "w", encoding="utf-8").write(content2)
print("  ✅  admin_site_budget.html saved")
print("\nDone! Refresh the budget page.")
