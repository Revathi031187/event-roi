import asyncio
import json
import os
import uuid as _uuid
from typing import Dict
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from models.schemas import GenerateRequest, GeneratePPTRequest, JobStartResponse
from services import pipeline_service, db_service
from services.ppt_service import generate_pptx, outline_as_in_ppt
from models.schemas import ReportOutline
from config import settings

router = APIRouter()

# In-memory PPT job queue: ppt_id → {job_id, outline}
_ppt_queue: Dict[str, dict] = {}


# ── Generation endpoints ──────────────────────────────────────────────────────

@router.post("/start", response_model=JobStartResponse)
async def start_generation(req: GenerateRequest, background_tasks: BackgroundTasks):
    job_id = pipeline_service.create_job()
    background_tasks.add_task(
        pipeline_service.run_pipeline,
        job_id=job_id,
        event_name=req.event_name,
        additional_context=req.additional_context or "",
        databricks_host=req.databricks_host,
        databricks_token=req.databricks_token,
        genie_space_id=req.genie_space_id,
    )
    return JobStartResponse(job_id=job_id, message=f"Pipeline started for: {req.event_name}")


@router.get("/stream/{job_id}")
async def stream_progress(job_id: str):
    q = pipeline_service.get_queue(job_id)
    if q is None:
        raise HTTPException(404, "Job not found")

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("complete", "error"):
                    # Small delay so the client receives and processes the event
                    # before the HTTP connection closes (prevents spurious onerror)
                    await asyncio.sleep(1)
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/result/{job_id}")
async def get_result(job_id: str):
    result = pipeline_service.get_result(job_id)
    if result is None:
        raise HTTPException(404, "Result not ready or job not found")
    return result


@router.post("/ppt-preview-outline")
async def ppt_preview_outline(outline: ReportOutline):
    """
    Return the outline after the same transforms used when building the PPTX
    (pipe-rows→table, funnel bullet derivation, number formatting). Use for slideshow preview parity.
    """
    return outline_as_in_ppt(outline)


# ── PPT generation ────────────────────────────────────────────────────────────

@router.post("/queue-ppt")
async def queue_ppt(req: GeneratePPTRequest):
    """Store the outline server-side and return a ppt_id for the SSE stream."""
    ppt_id = _uuid.uuid4().hex
    _ppt_queue[ppt_id] = {"job_id": req.job_id, "outline": req.outline.model_dump()}
    return {"ppt_id": ppt_id}


@router.get("/ppt-stream/{ppt_id}")
async def stream_ppt_generation(ppt_id: str):
    """SSE: emit slide_done events while building PPTX, then ppt_complete."""
    session = _ppt_queue.get(ppt_id)
    if not session:
        raise HTTPException(404, "PPT session not found or expired")

    outline = ReportOutline(**session["outline"])
    job_id = session["job_id"]
    total_slides = len(outline.slides) + 1  # cover + each content slide

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    result: dict = {}

    def _on_progress(slide_num, total, title):
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "slide_done", "slide": slide_num, "total": total, "title": title},
        )

    async def _generate():
        try:
            filename = await asyncio.to_thread(generate_pptx, outline, _on_progress)
            result["filename"] = filename
            result["url"] = f"/api/download/{filename}"
        except Exception as e:
            result["error"] = str(e)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(_generate())

    async def event_gen():
        # First byte ASAP so browsers/proxies do not stall; worker may still be starting.
        yield (
            f"data: {json.dumps({'type': 'ppt_started', 'total_slides': total_slides})}\n\n"
        )
        try:
            while True:
                try:
                    # Long gaps happen while python-pptx writes the file after the last slide_done.
                    # Subdivide the wait with pings so we never hit a single 120s ceiling.
                    item = await asyncio.wait_for(queue.get(), timeout=90.0)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ppt_ping'})}\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
            if result.get("filename"):
                await db_service.update_filenames(job_id, ppt_filename=result["filename"])
                yield f"data: {json.dumps({'type': 'ppt_complete', 'filename': result['filename'], 'url': result['url']})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'ppt_error', 'message': result.get('error', 'Generation failed')})}\n\n"
        finally:
            _ppt_queue.pop(ppt_id, None)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/generate-ppt")
async def generate_ppt_endpoint(req: GeneratePPTRequest):
    try:
        outline = ReportOutline(**req.outline.model_dump())
        filename = generate_pptx(outline)
        await db_service.update_filenames(req.job_id, ppt_filename=filename)
        return {"filename": filename, "url": f"/api/download/{filename}"}
    except Exception as e:
        raise HTTPException(500, f"PPT generation failed: {e}")


# ── Report history ────────────────────────────────────────────────────────────

@router.get("/reports")
async def list_reports():
    return await db_service.list_reports(limit=30)


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    data = await db_service.get_report(report_id)
    if not data:
        raise HTTPException(404, "Report not found")
    return data


@router.delete("/reports/{report_id}")
async def delete_report(report_id: str):
    deleted = await db_service.delete_report(report_id)
    if not deleted:
        raise HTTPException(404, "Report not found")
    return {"deleted": True}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def health():
    from services.genie_service import GenieService
    genie = GenieService()
    return {
        "status": "ok",
        "gemini_configured": bool(settings.gemini_api_key),
        "databricks_configured": bool(settings.databricks_host and settings.databricks_token),
        "demo_mode": genie.is_demo,
        "genie_space_id": settings.genie_space_id,
        "databricks_host": settings.databricks_host or "",
    }
