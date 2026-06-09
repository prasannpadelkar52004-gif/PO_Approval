content = open('app/api/v1/endpoints/html_routes.py').read()

# Find the PDF route and replace the try/except weasyprint block
old = '''    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={po.po_number}.pdf"}
        )
    except Exception as e:
        import traceback
        print("PDF ERROR:", traceback.format_exc())
        return Response(
            content=html_content,
            media_type="text/html"
        )'''

new = '''    try:
        from fpdf import FPDF
        import re

        class PDF(FPDF):
            pass

        pdf = PDF()
        pdf.add_page()
        pdf.set_margins(15, 15, 15)

        # Header
        pdf.set_fill_color(15, 27, 45)
        pdf.rect(0, 0, 210, 25, 'F')
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(15, 7)
        pdf.cell(100, 10, "P E E I - PO Approval System", ln=0)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(100, 160, 255)
        pdf.set_xy(130, 7)
        pdf.cell(60, 10, po.po_number, ln=0, align="R")
        pdf.ln(28)

        # Status & Date
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(90, 6, f"Status: {po.status.value.replace('_',' ').title()}", ln=0)
        pdf.cell(90, 6, f"Created: {po.created_at.strftime('%d %b %Y')}", ln=1, align="R")
        pdf.ln(3)

        # Section helper
        def section_title(title):
            pdf.set_fill_color(248, 250, 252)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(100, 116, 139)
            pdf.cell(0, 7, title.upper(), ln=1, fill=True)
            pdf.ln(2)

        def field(label, value, w=90):
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(148, 163, 184)
            pdf.cell(w, 5, label.upper(), ln=0)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(15, 23, 42)
            pdf.cell(w, 5, str(value or "-"), ln=1 if w==90 else 0)

        # PO Info
        section_title("PO Information")
        field("Vendor", po.vendor.name, 90)
        field("Requester", po.requester.full_name, 90)
        field("Category", po.po_category.replace("_"," ").title(), 90)
        field("Priority", po.priority.value.title(), 90)
        field("Department", po.department.name if po.department else "-", 90)
        field("Project/Site", po.project.name if po.project else "-", 90)
        field("Required By", po.required_by.strftime("%d %b %Y"), 90)
        field("Payment Terms", po.payment_terms or "-", 90)
        pdf.ln(3)

        # Description
        section_title("Description")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(51, 65, 85)
        pdf.multi_cell(0, 5, po.description or "-")
        pdf.ln(3)

        # Line Items
        section_title("Line Items")
        pdf.set_fill_color(248, 250, 252)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(100, 116, 139)
        col_widths = [8, 60, 15, 20, 22, 20, 20, 25]
        headers = ["#", "Description", "Unit", "Qty", "Rate", "Amount", "GST%", "Total"]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 6, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(15, 23, 42)
        for i, item in enumerate(po.line_items):
            pdf.cell(col_widths[0], 6, str(i+1), border=1)
            pdf.cell(col_widths[1], 6, item.description[:35], border=1)
            pdf.cell(col_widths[2], 6, item.unit_of_measure, border=1)
            pdf.cell(col_widths[3], 6, f"{float(item.quantity):.2f}", border=1, align="R")
            pdf.cell(col_widths[4], 6, f"{float(item.unit_rate):,.2f}", border=1, align="R")
            pdf.cell(col_widths[5], 6, f"{float(item.amount):,.2f}", border=1, align="R")
            pdf.cell(col_widths[6], 6, f"{float(item.gst_percent)}%", border=1, align="R")
            pdf.cell(col_widths[7], 6, f"{float(item.total):,.2f}", border=1, align="R")
            pdf.ln()

        # Totals
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(248, 250, 252)
        pdf.cell(165, 6, "Subtotal", border=1, fill=True, align="R")
        pdf.cell(25, 6, f"Rs.{float(po.subtotal):,.2f}", border=1, align="R", fill=True)
        pdf.ln()
        pdf.cell(165, 6, "GST", border=1, fill=True, align="R")
        pdf.cell(25, 6, f"Rs.{float(po.gst_amount):,.2f}", border=1, align="R", fill=True)
        pdf.ln()
        pdf.set_fill_color(219, 234, 254)
        pdf.set_text_color(37, 99, 235)
        pdf.cell(165, 7, "TOTAL AMOUNT", border=1, fill=True, align="R")
        pdf.cell(25, 7, f"Rs.{float(po.total_amount):,.2f}", border=1, align="R", fill=True)
        pdf.ln(8)

        # Approval Signatures
        section_title("Approval Signatures")
        pdf.set_text_color(15, 23, 42)
        sig_w = 180 / max(po.required_levels, 1)
        for level in range(1, po.required_levels + 1):
            step = next((s for s in po.approval_steps if s.level == level), None)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(15, 27, 45)
            label = f"L{level} Approval"
            pdf.cell(sig_w, 5, label, ln=0)
        pdf.ln(6)
        for level in range(1, po.required_levels + 1):
            step = next((s for s in po.approval_steps if s.level == level), None)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(100, 116, 139)
            if step and step.approver:
                txt = f"{step.approver.full_name}"
            else:
                txt = "Pending"
            pdf.cell(sig_w, 5, txt, ln=0)
        pdf.ln(8)

        # Footer
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(0, 5, f"Generated by PO Approval System | {po.po_number} | {po.created_at.strftime('%d %b %Y %H:%M')}", align="C")

        pdf_bytes = bytes(pdf.output())
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={po.po_number}.pdf"}
        )
    except Exception as e:
        import traceback
        print("PDF ERROR:", traceback.format_exc())
        return Response(content=f"PDF Error: {str(e)}", media_type="text/plain")'''

if old in content:
    content = content.replace(old, new)
    print("Fixed PDF route!")
else:
    print("Pattern not found")

open('app/api/v1/endpoints/html_routes.py', 'w').write(content)
print("Done!")
