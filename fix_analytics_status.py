content = open('app/api/v1/endpoints/html_routes.py').read()

# Fix 1: in_progress statuses
old1 = 'PurchaseOrder.status.in_(["submitted", "l1_approved", "l2_approved", "l3_approved", "l4_approved", "l5_approved"])'
if old1 not in content:
    old1 = 'PurchaseOrder.status.in_([POStatus.SUBMITTED.value, POStatus.L1_APPROVED.value, POStatus.L2_APPROVED.value, POStatus.L3_APPROVED.value, POStatus.L4_APPROVED.value, POStatus.L5_APPROVED.value])'

new1 = 'PurchaseOrder.status.in_(["submitted", "l1_approved", "l2_approved", "l3_approved", "l4_approved", "l5_approved"])'
if old1 in content:
    content = content.replace(old1, new1)
    print("Fixed in_progress statuses")
else:
    print("Pattern 1 not found")

# Fix 2: approved status
old2 = 'PurchaseOrder.status == POStatus.APPROVED'
new2 = 'PurchaseOrder.status == "approved"'
if old2 in content:
    content = content.replace(old2, new2)
    print("Fixed approved status")

# Fix 3: rejected status  
old3 = 'PurchaseOrder.status == POStatus.REJECTED'
new3 = 'PurchaseOrder.status == "rejected"'
if old3 in content:
    content = content.replace(old3, new3)
    print("Fixed rejected status")

# Fix 4: status_counts loop - compare with string value
old4 = 'PurchaseOrder.status == s.value'
new4 = 'PurchaseOrder.status == s'
if old4 in content:
    content = content.replace(old4, new4)
    print("Fixed status_counts")

open('app/api/v1/endpoints/html_routes.py', 'w').write(content)
print("Done!")
