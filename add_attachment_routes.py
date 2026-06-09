content = open('app/api/v1/endpoints/html_routes.py').read()

# Add upload and download routes before the analytics route
new_routes = '''
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

'''

# Insert before analytics route
insert_before = '# ── Analytics / Reports'
if insert_before in content:
    content = content.replace(insert_before, new_routes + insert_before)
    print("Added attachment routes!")
else:
    print("Insert point not found")

open('app/api/v1/endpoints/html_routes.py', 'w').write(content)
print("Done!")
