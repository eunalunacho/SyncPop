import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from models import (
    CreateTaskRequest,
    CreateTaskResponse,
    RetrySongRequest,
    RetrySongResponse,
    TaskStatusResponse,
)
from pipeline import (
    apply_post_processing,
    extract_video_id,
    get_cache_key,
    load_from_cache,
    task_manager,
)

# Load .env in backend only (GEMINI_API_KEY is never exposed to frontend)
load_dotenv()

app = FastAPI(
    title="SyncPop Live API",
    description="Gemini 4 Argon 1M Context Live Concert Lyrics & Sing-along Player",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
async def serve_spa() -> FileResponse:
    """단일 HTML 프론트엔드 서빙"""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(index_path, media_type="text/html; charset=utf-8")


@app.get("/api/v1/health")
async def health_check() -> dict:
    return {
        "status": "ok",
        "model": os.environ.get("GEMINI_MODEL", "gemini-4-argon"),
        "flash_model": os.environ.get("GEMINI_FLASH_MODEL", "gemini-3.8-flash"),
        "prompt_version": os.environ.get("PROMPT_VERSION", "v1.0"),
        "api_key_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
    }


@app.post("/api/v1/tasks", response_model=CreateTaskResponse)
async def create_task(req: CreateTaskRequest) -> CreateTaskResponse:
    """
    1단계: 입력 검증 및 캐시 키 생성
    - 유효하지 않은 유튜브 URL은 400 에러로 즉시 거부
    - 캐시 히트 시(force_process=False) 즉시 6단계(done)로 이동
    """
    try:
        video_id = extract_video_id(req.youtube_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_state = task_manager.create_or_reset_task(
        video_id=video_id,
        youtube_url=req.youtube_url,
        force_process=req.force_process,
    )

    if task_state["status"] == "queued":
        asyncio.create_task(task_manager.run_pipeline_worker(task_state["task_id"]))

    return CreateTaskResponse(
        task_id=task_state["task_id"],
        status=task_state["status"],
        cached=task_state["cached"],
    )


def _resolve_or_hydrate_task(task_id: str) -> dict:
    """
    백로그 1 반영: 메모리에 태스크가 없을 경우 디스크 캐시(cache/{task_id}.json)에서 동적 복원
    하드코딩된 Video ID 의존성을 제거하고 범용적으로 태스크를 복구합니다.
    """
    task = task_manager.get_task(task_id)
    if task:
        return task

    hydrated = task_manager.hydrate_task_from_disk(task_id)
    if hydrated:
        return hydrated

    raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")


@app.get("/api/v1/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """작업 상태 및 진행률(Progress) 조회"""
    task = _resolve_or_hydrate_task(task_id)
    return TaskStatusResponse(
        task_id=task["task_id"],
        status=task["status"],
        progress=task["progress"],
        fixed_count=task.get("fixed_count", 0),
        cached=task.get("cached", False),
    )


@app.get("/api/v1/tasks/{task_id}/result")
async def get_task_result(task_id: str) -> JSONResponse:
    """
    Phase 2 점진적 결과 반환:
    - 첫 번째 곡 초안이 준비된 시점(ready_to_play=True)부터 즉시 초기 결과를 반환하여
      10~15초 내에 플레이어 화면을 열 수 있도록 지원합니다.
    """
    task = _resolve_or_hydrate_task(task_id)
    if not task.get("result"):
        raise HTTPException(
            status_code=202,
            detail=f"Task is currently '{task['status']}' ({task['progress']})",
        )
    return JSONResponse(content=task["result"])


@app.post("/api/v1/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    """백로그 2: 진행 중인 분석 작업을 취소하고 안전하게 중단"""
    cancelled = task_manager.cancel_task(task_id)
    return {"status": "cancelled" if cancelled else "not_found", "task_id": task_id}


@app.post("/api/v1/tasks/{task_id}/segments/{seg_id}/prioritize")
async def prioritize_segment(task_id: str, seg_id: str) -> dict:
    """Phase 2 Step 3-① JIT(On-Demand) 우선순위 요청"""
    task_manager.prioritize_segment(task_id, seg_id)
    return {"status": "prioritized", "task_id": task_id, "segment_id": seg_id}


@app.get("/api/v1/tasks/{task_id}/logs")
async def stream_task_logs(task_id: str, request: Request) -> StreamingResponse:
    """
    진행 로그 및 실시간 가사 패칭(lyric_patch / song_ready / ready_to_play) SSE 스트리밍
    """
    task = _resolve_or_hydrate_task(task_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        task["subscribers"].append(queue)
        try:
            # 기존 누적 로그 먼저 전송
            for entry in list(task.get("log_history", [])):
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"

            if task["status"] in ("done", "failed"):
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    if item.get("status") in ("done", "failed"):
                        break
                except asyncio.TimeoutError:
                    if task["status"] in ("done", "failed"):
                        break
                    yield ": keep-alive\n\n"
        finally:
            if queue in task["subscribers"]:
                task["subscribers"].remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/tasks/{task_id}/songs/{seg_id}/retry", response_model=RetrySongResponse)
async def retry_single_song(
    task_id: str,
    seg_id: str,
    req: RetrySongRequest = RetrySongRequest(),
) -> RetrySongResponse:
    """
    데모 시연용: 곡 1개 실시간 재처리 및 자율 검증 루프(~14초) 구동
    """
    task = _resolve_or_hydrate_task(task_id)
    task["status"] = "processing"
    task["progress"] = f"0/1 song ({seg_id})"
    task["cancelled"] = False
    task["log_history"] = []
    asyncio.create_task(task_manager.run_single_song_live_retry(task["task_id"], seg_id))
    return RetrySongResponse(
        status="queued",
        message="Demo validation started",
        task_id=task["task_id"],
        segment_id=seg_id,
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
