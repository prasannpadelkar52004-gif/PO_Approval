content = open('app/api/v1/endpoints/html_routes.py').read()

old = '''        po = await POService.create_po(session, po_data, user, chains)

        # If submit (not just draft), also submit for approval'''

new = '''        po = await POService.create_po(session, po_data, user, chains)

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
                ))
            await session.commit()
        except Exception as _att_e:
            import logging
            logging.getLogger(__name__).warning("Attachment save failed: %s", _att_e)

        # If submit (not just draft), also submit for approval'''

if old in content:
    content = content.replace(old, new)
    print("Fixed! Attachment saving added.")
else:
    print("Pattern not found")

open('app/api/v1/endpoints/html_routes.py', 'w').write(content)
print("Done!")
