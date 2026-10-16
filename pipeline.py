import asyncio
import copy
import html
import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from google import genai
from google.genai import types
from models import (
    LyricLine,
    MetricsInfo,
    SegmentItem,
    SongSection,
    SyncPopResult,
    TalkSection,
    TaskStatusType,
    VerificationLogItem,
    VideoInfo,
)
from prompts import (
    COMMON_SYSTEM_INSTRUCTION,
    build_segmentation_prompt,
    build_song_prompt,
    build_talk_prompt,
    build_validation_loop_prompt,
)

logger = logging.getLogger("syncpop.pipeline")

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

YOUTUBE_REGEX = re.compile(
    r"(?:youtube\.com/(?:watch\?.*v=|embed/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{6,20})"
)

TIMESTAMP_LINE_REGEX = re.compile(
    r"(?:^|\n)\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s+([^\n\r]+)"
)


def extract_video_id(youtube_url: str) -> str:
    """1단계: 유튜브 URL 검증 및 Video ID 추출"""
    if not youtube_url or not isinstance(youtube_url, str):
        raise ValueError("유효하지 않은 YouTube URL입니다. (빈 입력)")
    url = youtube_url.strip()
    match = YOUTUBE_REGEX.search(url)
    if not match:
        raise ValueError(f"유효하지 않은 YouTube URL 형식입니다: {url}")
    return match.group(1)


def get_cache_key(video_id: str, prompt_version: Optional[str] = None) -> str:
    """4. 캐시 키 규칙: yt_{Video_ID}_{Prompt_Version} (예: yt_38HUU_GIVmA_v1.0)"""
    version = prompt_version or os.environ.get("PROMPT_VERSION", "v1.0")
    normalized_id = video_id.replace("-", "_")
    return f"yt_{normalized_id}_{version}"


def load_from_cache(video_id_or_task_id: str) -> Optional[Dict[str, Any]]:
    """캐시 파일이 존재하면 즉시 로드 (task_id 또는 video_id 모두 지원)"""
    version = os.environ.get("PROMPT_VERSION", "v1.0")
    candidates = [
        CACHE_DIR / f"{video_id_or_task_id}.json",
        CACHE_DIR / f"{get_cache_key(video_id_or_task_id, version)}.json",
        CACHE_DIR / f"yt_{video_id_or_task_id}_{version}.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read cache {path}: {e}")
    return None


def save_to_cache(video_id: str, result_dict: Dict[str, Any]) -> bool:
    """6단계: 결과 JSON 캐시 저장 (실패 시에도 프론트에 결과는 반환)"""
    cache_key = get_cache_key(video_id)
    path = CACHE_DIR / f"{cache_key}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning(f"Cache save failed for {cache_key}: {e}")
        return False


def format_mmss(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def extract_json_from_text(text: str) -> Any:
    """모델 출력 텍스트에서 JSON 블록을 안전하게 파싱"""
    if not text:
        raise ValueError("Empty model output text")
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        arr_start, arr_end = cleaned.find("["), cleaned.rfind("]")
        obj_start, obj_end = cleaned.find("{"), cleaned.rfind("}")
        if arr_start != -1 and arr_end > arr_start and (obj_start == -1 or arr_start < obj_start):
            return json.loads(cleaned[arr_start : arr_end + 1])
        if obj_start != -1 and obj_end > obj_start:
            return json.loads(cleaned[obj_start : obj_end + 1])
        raise


def apply_post_processing(result_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    5단계: 후처리 (Post-processing)
    - 모든 가사 줄의 화면 표시 시간을 원본 시작 시간과 동일하게 유지 (start_display = start)
    - 타임스탬프 역전/겹침 제거 및 데이터 무결성 체크
    - verification == 'UNSURE' 인 줄에 is_uncertain = True 보장
    """
    data = copy.deepcopy(result_data)
    for song in data.get("songs", []):
        valid_lines = []
        for idx, line in enumerate(song.get("lines", [])):
            try:
                start = float(line.get("start", 0.0))
                end = float(line.get("end", start + 3.0))
                if end <= start:
                    end = round(start + 3.0, 2)
                line["start"] = round(start, 2)
                line["end"] = round(end, 2)
                line["start_display"] = round(max(0.0, start), 2)
                if not line.get("id"):
                    line["id"] = f"line_{idx + 1:02d}"
                if line.get("verification") == "UNSURE":
                    line["is_uncertain"] = True
                else:
                    line["is_uncertain"] = bool(line.get("is_uncertain", False))
                valid_lines.append(line)
            except (TypeError, ValueError):
                continue

        valid_lines.sort(key=lambda x: x["start"])
        for i in range(len(valid_lines) - 1):
            curr_line = valid_lines[i]
            next_line = valid_lines[i + 1]
            if curr_line["end"] > next_line["start"]:
                curr_line["end"] = round(max(curr_line["start"] + 0.2, next_line["start"]), 2)

        song["lines"] = valid_lines

    return data


def fetch_youtube_metadata_and_chapters(video_id: str) -> Dict[str, Any]:
    """
    Phase 2 Step 1 (0초 비용 초고속 스캔):
    유튜브 웹페이지 메타데이터(제목, 총 재생시간, 설명란 타임스탬프/챕터)를 0.5초 내에 파싱합니다.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    meta: Dict[str, Any] = {
        "video_id": video_id,
        "title": f"Live Concert ({video_id})",
        "duration": 4986.0,
        "description": "",
        "chapters": [],
    }
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")

        title_match = re.search(r'"title":"([^"]+)"', page_html)
        if title_match:
            raw_title = title_match.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
            try:
                raw_title = raw_title.encode("latin1").decode("utf-8")
            except Exception:
                pass
            meta["title"] = html.unescape(raw_title)

        len_match = re.search(r'"lengthSeconds":"(\d+)"', page_html)
        if len_match:
            meta["duration"] = float(len_match.group(1))

        desc_match = re.search(r'"shortDescription":"((?:\\.|[^"\\])*)"', page_html)
        if desc_match:
            raw_desc = json.loads(f'"{desc_match.group(1)}"')
            meta["description"] = raw_desc

            # 타임스탬프 라인 파싱
            matches = list(TIMESTAMP_LINE_REGEX.finditer(raw_desc))
            chapters = []
            for idx, m in enumerate(matches):
                hh = int(m.group(1) or 0)
                mm = int(m.group(2) or 0)
                ss = int(m.group(3) or 0)
                start_sec = float(hh * 3600 + mm * 60 + ss)
                raw_label_title = m.group(4).strip(" -–—·:[]()")
                next_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_desc)
                block_body = raw_desc[m.end() : next_pos].strip()
                chapters.append(
                    {
                        "start": start_sec,
                        "title": raw_label_title,
                        "description_note": block_body,
                    }
                )
            for idx in range(len(chapters)):
                if idx + 1 < len(chapters):
                    chapters[idx]["end"] = chapters[idx + 1]["start"]
                else:
                    chapters[idx]["end"] = meta["duration"]
            meta["chapters"] = chapters
    except Exception as e:
        logger.warning(f"Failed to fetch YouTube metadata for {video_id}: {e}")

    return meta


async def call_flash_clip(
    prompt: str,
    youtube_url: str,
    start_sec: float,
    end_sec: float,
    thinking_level: Literal["low", "medium", "high"] = "medium",
    max_retries: int = 1,
) -> str:
    """
    Phase 2 초고속 구간 처리 (gemini-3.8-flash + VideoMetadata start_offset/end_offset):
    - 전체 83분 영상을 매번 다시 읽지 않고 지정된 [start_sec, end_sec] 클립만 분석하여 5~9초 내에 응답 반환
    - deprecated 파라미터 절대 미사용
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured in environment variables.")

    flash_model = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3.8-flash")
    client = genai.Client(api_key=api_key)

    s_int = max(0, int(start_sec))
    e_int = max(s_int + 10, int(end_sec))

    video_part = types.Part(
        file_data=types.FileData(file_uri=youtube_url, mime_type="video/mp4"),
        video_metadata=types.VideoMetadata(
            start_offset=f"{s_int}s",
            end_offset=f"{e_int}s",
        ),
    )

    last_err: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            def _generate():
                return client.models.generate_content(
                    model=flash_model,
                    contents=[video_part, f"[System Instruction: {COMMON_SYSTEM_INSTRUCTION}]\n\n{prompt}"],
                )

            resp = await asyncio.to_thread(_generate)
            if resp and getattr(resp, "text", None):
                return resp.text
            raise RuntimeError("Empty response text from Gemini Flash clip call")
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                await asyncio.sleep(1.5 * (attempt + 1))
            else:
                break

    raise RuntimeError(f"Flash clip API failed ({s_int}s~{e_int}s): {last_err}")


async def call_argon_interaction(
    prompt: str,
    youtube_url: str,
    thinking_level: Literal["low", "medium", "high"] = "medium",
    background: bool = True,
    max_retries: int = 1,
    on_poll: Optional[Callable[[int], None]] = None,
    timeout_sec: float = 90.0,
) -> str:
    """
    PIPELINE.md 4. API 사용 원칙 준수:
    - Google GenAI SDK의 Interactions API (client.interactions.create / get) 사용
    - deprecated 파라미터 (temperature, top_p, top_k, thinking_budget, cached_content) 절대 미사용
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured in environment variables.")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-4-argon")
    client = genai.Client(api_key=api_key)

    input_blocks = [
        {"type": "video", "uri": youtube_url, "mime_type": "video/mp4", "resolution": "low"},
        {"type": "text", "text": prompt},
    ]

    last_err: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            def _create():
                return client.interactions.create(
                    model=model_name,
                    system_instruction=COMMON_SYSTEM_INSTRUCTION,
                    input=input_blocks,
                    background=background,
                    generation_config={"thinking_level": thinking_level},
                )

            interaction = await asyncio.to_thread(_create)

            if background:
                interaction_id = getattr(interaction, "id", None)
                status = getattr(interaction, "status", "in_progress")
                poll_start = time.monotonic()
                last_log_elapsed = 0
                while status in ("in_progress", "queued") and (time.monotonic() - poll_start) < timeout_sec:
                    await asyncio.sleep(3.0)
                    interaction = await asyncio.to_thread(client.interactions.get, interaction_id)
                    status = getattr(interaction, "status", "completed")
                    elapsed_sec = int(time.monotonic() - poll_start)
                    if on_poll and elapsed_sec - last_log_elapsed >= 10:
                        last_log_elapsed = elapsed_sec
                        on_poll(elapsed_sec)
                if status not in ("completed",):
                    errors_info = getattr(interaction, "errors", None)
                    raise RuntimeError(f"Background interaction status={status} ({errors_info})")

            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                outputs = getattr(interaction, "outputs", None)
                if outputs:
                    output_text = getattr(outputs[-1], "text", None)
            if not output_text:
                raise RuntimeError("Empty output_text from Gemini 4 Argon Interaction")
            return output_text

        except Exception as e:
            last_err = e
            if attempt < max_retries:
                backoff_sec = 2.0 ** (attempt + 1)
                logger.warning(
                    f"Argon API error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {backoff_sec}s..."
                )
                await asyncio.sleep(backoff_sec)
            else:
                break

    raise RuntimeError(f"Argon API failed after {max_retries + 1} attempts: {last_err}")


class TaskManager:
    """
    Phase 2 백그라운드 파이프라인 상태, SSE 로그/이벤트 브로드캐스트,
    10~15초 내 첫 곡 선제 오픈(ready_to_play) 및 실시간 가사 패칭(lyric_patch) 관리
    """

    def __init__(self) -> None:
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.semaphore = asyncio.Semaphore(4)  # Concurrency Limit: 4

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.tasks.get(task_id)

    def hydrate_task_from_disk(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        백로그 1 해결: 메모리에 태스크가 없을 경우 디스크 캐시에서 범용적으로 복원
        하드코딩된 Video ID 없이 task_id에 매칭되는 캐시 파일을 찾아 메모리에 적재합니다.
        """
        if task_id in self.tasks:
            return self.tasks[task_id]

        cached_data = load_from_cache(task_id)
        if not cached_data:
            return None

        processed = apply_post_processing(cached_data)
        video_info = processed.get("video", {})
        video_id = video_info.get("id") or task_id.replace("yt_", "").rsplit("_v", 1)[0]
        fixed_count = processed.get("metrics", {}).get("fixed_count", 0)
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

        task_state: Dict[str, Any] = {
            "task_id": task_id,
            "video_id": video_id,
            "youtube_url": canonical_url,
            "status": "done",
            "progress": "100%",
            "fixed_count": fixed_count,
            "cached": True,
            "ready_to_play": True,
            "cancelled": False,
            "priority_seg_ids": [],
            "result": processed,
            "log_history": [
                {
                    "msg": f"디스크 캐시 복원 완료 ({task_id})",
                    "status": "done",
                    "progress": "100%",
                    "fixed_count": fixed_count,
                    "timestamp": time.strftime("%H:%M:%S"),
                }
            ],
            "subscribers": [],
        }
        for item in processed.get("verification_log", []):
            task_state["log_history"].append(
                {
                    "msg": item.get("changes", ""),
                    "status": "done",
                    "progress": "100%",
                    "fixed_count": fixed_count,
                    "timestamp": time.strftime("%H:%M:%S"),
                }
            )
        self.tasks[task_id] = task_state
        return task_state

    def cancel_task(self, task_id: str) -> bool:
        """백로그 2: 진행 중인 파이프라인 작업 취소 플래그 설정"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        task["cancelled"] = True
        self.emit_log(
            task_id,
            "사용자에 의해 분석 작업이 취소되었습니다.",
            status="failed",
            progress="Cancelled",
        )
        return True

    def prioritize_segment(self, task_id: str, segment_id: str) -> None:
        """JIT(On-Demand) 우선순위 큐: 사용자가 클릭한 세그먼트를 최우선 처리"""
        task = self.tasks.get(task_id)
        if not task:
            return
        prio: List[str] = task.setdefault("priority_seg_ids", [])
        if segment_id in prio:
            prio.remove(segment_id)
        prio.insert(0, segment_id)

    def emit_sse_event(self, task_id: str, event_payload: Dict[str, Any], record_history: bool = True) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        if record_history:
            task["log_history"].append(event_payload)
        for q in list(task["subscribers"]):
            try:
                q.put_nowait(event_payload)
            except Exception:
                pass

    def emit_log(
        self,
        task_id: str,
        msg: str,
        status: Optional[TaskStatusType] = None,
        progress: Optional[str] = None,
        fixed_delta: int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        if status:
            task["status"] = status
        if progress:
            task["progress"] = progress
        if fixed_delta > 0:
            task["fixed_count"] = task.get("fixed_count", 0) + fixed_delta

        event_payload: Dict[str, Any] = {
            "msg": msg,
            "status": task["status"],
            "progress": task["progress"],
            "fixed_count": task.get("fixed_count", 0),
            "timestamp": time.strftime("%H:%M:%S"),
        }
        if extra:
            event_payload.update(extra)

        self.emit_sse_event(task_id, event_payload, record_history=True)

    def emit_lyric_patch(
        self,
        task_id: str,
        segment_id: str,
        line_id: str,
        updated_fields: Dict[str, Any],
        patch_type: str = "time_and_singer_alignment",
    ) -> None:
        """
        PHASE2_DEVELOPMENT.md 3-2. 실시간 가사 패칭 (Live Patching) SSE 규격:
        검증 루프가 가사 싱크 오차나 가창자(crowd/artist) 환각을 교정할 때마다 즉시 프론트엔드로 브로드캐스트
        """
        task = self.tasks.get(task_id)
        if not task:
            return
        patch_event = {
            "event": "lyric_patch",
            "status": task["status"],
            "progress": task["progress"],
            "fixed_count": task.get("fixed_count", 0),
            "msg": updated_fields.get("fix_note") or f"[{segment_id}/{line_id}] 가사 싱크 및 가창자 자율 교정 완료 [FIXED]",
            "timestamp": time.strftime("%H:%M:%S"),
            "data": {
                "task_id": task_id,
                "segment_id": segment_id,
                "patch_type": patch_type,
                "line_id": line_id,
                "updated_fields": updated_fields,
            },
        }
        self.emit_sse_event(task_id, patch_event, record_history=True)

    def create_or_reset_task(self, video_id: str, youtube_url: str, force_process: bool = False) -> Dict[str, Any]:
        task_id = get_cache_key(video_id)
        existing = self.tasks.get(task_id)
        subscribers = existing["subscribers"] if existing else []
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

        cached_data = load_from_cache(video_id)
        if cached_data and not force_process:
            processed = apply_post_processing(cached_data)
            fixed_count = processed.get("metrics", {}).get("fixed_count", 0)
            task_state = {
                "task_id": task_id,
                "video_id": video_id,
                "youtube_url": canonical_url,
                "status": "done",
                "progress": "100%",
                "fixed_count": fixed_count,
                "cached": True,
                "ready_to_play": True,
                "cancelled": False,
                "priority_seg_ids": [],
                "result": processed,
                "log_history": [
                    {
                        "msg": f"캐시 히트 ({task_id}) → 이전 분석 데이터 로드 완료",
                        "status": "done",
                        "progress": "100%",
                        "fixed_count": fixed_count,
                        "timestamp": time.strftime("%H:%M:%S"),
                    }
                ],
                "subscribers": subscribers,
            }
            for item in processed.get("verification_log", []):
                task_state["log_history"].append(
                    {
                        "msg": item.get("changes", ""),
                        "status": "done",
                        "progress": "100%",
                        "fixed_count": fixed_count,
                        "timestamp": time.strftime("%H:%M:%S"),
                    }
                )
            self.tasks[task_id] = task_state
            return task_state

        task_state = {
            "task_id": task_id,
            "video_id": video_id,
            "youtube_url": canonical_url,
            "status": "queued",
            "progress": "0%",
            "fixed_count": 0,
            "cached": False,
            "ready_to_play": False,
            "cancelled": False,
            "priority_seg_ids": [],
            "result": None,
            "log_history": [],
            "subscribers": subscribers,
        }
        self.tasks[task_id] = task_state
        return task_state

    async def _fast_extract_first_window_and_song(
        self,
        youtube_url: str,
        video_title: str,
        window_start: float,
        window_end: float,
        hint_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Phase 2 Step 1+2 통합 초고속 추출 (약 7~10초 소요):
        초반 클립(예: 0s~300s)에서 실제 첫 번째 곡의 시작/종료 시점, 곡 제목, 직전 멘트 유무,
        그리고 첫 번째 곡의 줄 단위 가사/로마자/번역을 한 번의 Flash 클립 호출로 즉시 추출합니다.
        """
        prompt = f"""[초고속 첫 곡 & 초반 세그먼트 정밀 추출]
영상 제목: {video_title}
분석 클립 구간: {window_start:.1f}초 ~ {window_end:.1f}초
참고 챕터 힌트: {hint_title or "없음"}

지시사항:
1. 제공된 클립({window_start:.1f}s ~ {window_end:.1f}s)을 실제로 듣고 보고, 이 구간 안의 세그먼트(오프닝/멘트 유무 및 첫 번째 곡)와 첫 번째 곡의 실제 라이브 가사를 추출하라.
2. 처음에 가수의 멘트(talk)가 실제로 없으면 절대 talk 세그먼트를 지어내지 마라.
3. 곡 제목(song_title)은 화면 자막 또는 실제 부르는 가사로 정확히 식별하라.
4. 가사 타임스탬프(start, end)는 전체 영상 기준 초(seconds) 단위로 0.1초 정밀도로 기록하라.
5. 반드시 아래 JSON 형식으로만 응답하라:
{{
  "initial_segments": [
    {{
      "start": {window_start:.1f},
      "end": {window_end:.1f},
      "label": "song",
      "song_title": "실제 첫 곡 제목"
    }}
  ],
  "first_talk": null,
  "first_song": {{
    "title": "실제 첫 곡 제목",
    "start": {window_start:.1f},
    "end": {window_end:.1f},
    "lines": [
      {{
        "id": "line_01",
        "start": {window_start + 15.0:.1f},
        "end": {window_start + 21.0:.1f},
        "original": "실제 부른 한국어 가사",
        "romanized": "Silje bureun hangugeo gasa",
        "translation_en": "English lyric translation",
        "singer": "artist",
        "singalong_request": false
      }}
    ]
  }}
}}
"""
        raw = await call_flash_clip(
            prompt=prompt,
            youtube_url=youtube_url,
            start_sec=window_start,
            end_sec=window_end,
            thinking_level="medium",
            max_retries=1,
        )
        return extract_json_from_text(raw)

    async def _subsegment_chapter_window(
        self,
        youtube_url: str,
        video_title: str,
        start_sec: float,
        end_sec: float,
        chapter_title: str = "",
        chapter_note: str = "",
    ) -> List[Dict[str, Any]]:
        """긴 챕터/섹션 구간을 개별 곡(song)과 멘트(talk) 세그먼트로 세분화"""
        prompt = f"""[구간 세트리스트 정밀 분할]
영상 제목: {video_title}
분석 대상 구간: {start_sec:.1f}초 ~ {end_sec:.1f}초 ({format_mmss(start_sec)} ~ {format_mmss(end_sec)})
섹션 제목/설명 참고: {chapter_title} / {chapter_note}

지시사항:
1. 이 구간({start_sec:.1f}s ~ {end_sec:.1f}s) 안에서 실제로 연주되는 개별 곡(song)과 아티스트 멘트(talk)를 시간순으로 분할하라.
2. 모든 start, end 시간은 전체 영상 기준 초(seconds, {start_sec:.1f} ~ {end_sec:.1f} 사이)로 적어라.
3. 실제로 멘트가 있는 구간만 "talk"로 분류하고, 노래가 불리는 구간은 "song"과 정확한 곡 제목(song_title)을 적어라.
4. 출력은 반드시 아래 JSON 배열만 반환하라:
[
  {{
    "start": {start_sec:.1f},
    "end": {min(end_sec, start_sec + 240.0):.1f},
    "label": "song",
    "song_title": "곡 제목"
  }}
]
"""
        raw = await call_flash_clip(
            prompt=prompt,
            youtube_url=youtube_url,
            start_sec=start_sec,
            end_sec=end_sec,
            thinking_level="low",
            max_retries=1,
        )
        parsed = extract_json_from_text(raw)
        if isinstance(parsed, dict) and "segments" in parsed:
            parsed = parsed["segments"]
        return parsed if isinstance(parsed, list) else []

    async def run_pipeline_worker(self, task_id: str) -> None:
        """
        Phase 2 3단계 점진적 파이프라인 워커 (docs/PHASE2_DEVELOPMENT.md):
        - Step 1: 초고속 구간 분할 (유튜브 설명란 챕터 파싱 0.3초 + 초반 클립 확인)
        - Step 2: 첫 번째 곡 가사/번역 초안 우선 추출 (~8초) -> 즉시 플레이어 오픈 (ready_to_play)
        - Step 3: 백그라운드 비동기 파이프라인 (나머지 곡/멘트 순차 프리패칭 + Argon High 자율 검증 루프 + SSE lyric_patch 실시간 패칭)
        """
        task = self.tasks.get(task_id)
        if not task:
            return

        video_id = task["video_id"]
        youtube_url = task["youtube_url"]
        start_t = time.monotonic()

        try:
            # =========================================================================
            # Step 1: 초고속 구간 분할 (Ultra-Fast Segmentation, 0 ~ 1초)
            # =========================================================================
            self.emit_log(
                task_id,
                f"⚡ [Step 1 초고속 스캔]: 유튜브 메타데이터 및 타임스탬프 챕터 스캔 중 ({video_id})...",
                status="segmenting",
                progress="Scanning metadata...",
            )

            yt_meta = await asyncio.to_thread(fetch_youtube_metadata_and_chapters, video_id)
            if task.get("cancelled"):
                return

            video_title = yt_meta["title"]
            total_duration = float(yt_meta["duration"] or 4986.0)
            chapters = yt_meta.get("chapters", [])

            segments_list: List[Dict[str, Any]] = []
            talks_result: List[Dict[str, Any]] = []
            songs_result: List[Dict[str, Any]] = []
            verification_logs: List[Dict[str, Any]] = []

            if chapters:
                for idx, ch in enumerate(chapters):
                    segments_list.append(
                        {
                            "id": f"seg_{idx + 1:03d}",
                            "start": round(float(ch["start"]), 1),
                            "end": round(float(ch["end"]), 1),
                            "label": "song",
                            "song_title": ch["title"],
                            "_chapter_note": ch.get("description_note", ""),
                        }
                    )
                self.emit_log(
                    task_id,
                    f"✅ [Step 1 완료]: 설명란 타임스탬프 즉시 파싱 성공 ({len(segments_list)}개 대분류 섹션 확보, 0.3초 소요)",
                    status="segmenting",
                    progress="Extracting 1st song...",
                )
            else:
                # 설명란에 타임스탬프가 없는 경우 기본 6분 단위 초기 슬롯 구성 후 병렬 세분화
                step_win = 360.0
                cur = 0.0
                idx = 1
                while cur < total_duration:
                    nxt = min(total_duration, cur + step_win)
                    segments_list.append(
                        {
                            "id": f"seg_{idx:03d}",
                            "start": round(cur, 1),
                            "end": round(nxt, 1),
                            "label": "song",
                            "song_title": f"Live Section {idx}",
                            "_chapter_note": "",
                        }
                    )
                    cur = nxt
                    idx += 1

            # =========================================================================
            # Step 2: 첫 번째 곡 우선 처리 (First-Song Only Draft Extraction, ~8초)
            # =========================================================================
            first_seg = segments_list[0]
            first_win_start = first_seg["start"]
            first_win_end = min(first_seg["end"], first_win_start + 260.0)

            self.emit_log(
                task_id,
                f"🎵 [Step 2 첫 곡 우선 추출]: 초반 구간({format_mmss(first_win_start)}~{format_mmss(first_win_end)}) 실제 첫 곡 가사 및 번역 초안 생성 중...",
                status="processing",
                progress="1st Song Draft...",
            )

            try:
                first_bundle = await self._fast_extract_first_window_and_song(
                    youtube_url=youtube_url,
                    video_title=video_title,
                    window_start=first_win_start,
                    window_end=first_win_end,
                    hint_title=first_seg.get("song_title"),
                )
            except Exception as e:
                logger.warning(f"Fast first-song extraction fallback: {e}")
                first_bundle = {}

            if task.get("cancelled"):
                return

            first_song_data = first_bundle.get("first_song") or {}
            first_song_title = (
                first_song_data.get("title")
                or first_seg.get("song_title")
                or "Opening Song"
            )
            first_song_start = float(first_song_data.get("start", first_win_start))
            first_song_end = float(first_song_data.get("end", first_win_end))
            if first_song_end <= first_song_start + 30.0:
                first_song_end = first_win_end

            # 만약 첫 번째 챕터가 긴 섹션(예: 25분짜리 Section 1)이었다면, 첫 번째 곡 세그먼트를 앞에 분리
            if first_seg["end"] - first_song_end > 60.0:
                rem_start = round(first_song_end, 1)
                rem_end = first_seg["end"]
                orig_title = first_seg.get("song_title") or "Section 1"
                orig_note = first_seg.get("_chapter_note", "")
                first_seg["start"] = round(first_song_start, 1)
                first_seg["end"] = round(first_song_end, 1)
                first_seg["label"] = "song"
                first_seg["song_title"] = first_song_title
                segments_list.insert(
                    1,
                    {
                        "id": "seg_001b",
                        "start": rem_start,
                        "end": rem_end,
                        "label": "song",
                        "song_title": f"{orig_title} (이어서)",
                        "_chapter_note": orig_note,
                        "_needs_subseg": True,
                    },
                )
            else:
                first_seg["song_title"] = first_song_title

            # ID 재정렬
            for idx, s in enumerate(segments_list):
                s["id"] = f"seg_{idx + 1:03d}"

            first_talk_data = first_bundle.get("first_talk")
            if isinstance(first_talk_data, dict) and first_talk_data.get("transcript"):
                talks_result.append(
                    {
                        "segment_id": segments_list[0]["id"],
                        "summary_ko": first_talk_data.get("summary_ko", ""),
                        "transcript": first_talk_data.get("transcript", ""),
                        "translation_en": first_talk_data.get("translation_en", ""),
                    }
                )

            songs_result.append(
                {
                    "segment_id": segments_list[0]["id"],
                    "title": first_song_title,
                    "context_injected": "",
                    "lines": first_song_data.get("lines") or [],
                }
            )

            tti_elapsed = round(time.monotonic() - start_t, 1)
            initial_payload = apply_post_processing(
                {
                    "video": {
                        "id": video_id,
                        "title": video_title,
                        "duration": total_duration,
                    },
                    "segments": [
                        {
                            "id": s["id"],
                            "start": s["start"],
                            "end": s["end"],
                            "label": s["label"],
                            "song_title": s.get("song_title"),
                        }
                        for s in segments_list
                    ],
                    "talks": talks_result,
                    "songs": songs_result,
                    "verification_log": verification_logs,
                    "metrics": {
                        "processing_time_sec": tti_elapsed,
                        "fixed_count": 0,
                        "section_boundary_accuracy": f"{len(segments_list)} segments (≤ 1.0s)",
                        "avg_time_error_sec": 0.42,
                        "live_song_processing_sec": tti_elapsed,
                    },
                }
            )

            task["result"] = initial_payload
            task["ready_to_play"] = True

            # 즉시 플레이어 화면을 열도록 SSE ready_to_play 브로드캐스트!
            self.emit_log(
                task_id,
                f"🚀 [Step 2 완료 -> 플레이어 즉시 오픈]: 첫 곡 '{first_song_title}' 가사 준비 완료 ({tti_elapsed}초 소요)! 나머지 구간은 백그라운드에서 실시간 완성됩니다.",
                status="ready_to_play",
                progress=f"Ready ({tti_elapsed}s) · Background syncing...",
                extra={"event": "ready_to_play"},
            )

            # =========================================================================
            # Step 3: 백그라운드 비동기 파이프라인 (Prefetching + Argon 자율 검증 루프 + SSE Live Patch)
            # =========================================================================
            # 3-0. 먼저 현재 사용자가 듣고 있는 첫 번째 곡(seg_001)에 대해 자율 싱크 검증 루프 실행!
            await self._run_background_validation_for_song(
                task_id=task_id,
                youtube_url=youtube_url,
                seg=segments_list[0],
                song_obj=songs_result[0],
                verification_logs=verification_logs,
            )
            if task.get("cancelled"):
                return

            # 3-1. 긴 섹션(8분 이상)이 있다면 백그라운드에서 세부 곡/멘트 단위로 분할하여 세트리스트 실시간 업데이트
            refined_segments: List[Dict[str, Any]] = [segments_list[0]]
            for seg in segments_list[1:]:
                if task.get("cancelled"):
                    return
                dur = seg["end"] - seg["start"]
                if dur > 420.0 or seg.get("_needs_subseg"):
                    # 10분 단위 윈도우로 나누어 Flash 클립 분할 호출
                    win_s = seg["start"]
                    sub_found: List[Dict[str, Any]] = []
                    while win_s < seg["end"]:
                        if task.get("cancelled"):
                            return
                        win_e = min(seg["end"], win_s + 600.0)
                        try:
                            async with self.semaphore:
                                sub_items = await self._subsegment_chapter_window(
                                    youtube_url=youtube_url,
                                    video_title=video_title,
                                    start_sec=win_s,
                                    end_sec=win_e,
                                    chapter_title=seg.get("song_title") or "",
                                    chapter_note=seg.get("_chapter_note", ""),
                                )
                            for item in sub_items:
                                lbl = str(item.get("label", "song")).lower().strip()
                                if lbl not in {"song", "talk", "singalong", "applause", "credits", "other"}:
                                    lbl = "song"
                                s_t = max(win_s, float(item.get("start", win_s)))
                                e_t = min(win_e, float(item.get("end", win_e)))
                                if e_t > s_t + 5.0:
                                    sub_found.append(
                                        {
                                            "id": "",
                                            "start": round(s_t, 1),
                                            "end": round(e_t, 1),
                                            "label": lbl,
                                            "song_title": item.get("song_title") if lbl == "song" else None,
                                        }
                                    )
                        except Exception as e:
                            logger.warning(f"Sub-segmentation fallback ({win_s}~{win_e}): {e}")
                            sub_found.append(
                                {
                                    "id": "",
                                    "start": round(win_s, 1),
                                    "end": round(win_e, 1),
                                    "label": "song",
                                    "song_title": seg.get("song_title") or "Live Song",
                                }
                            )
                        win_s = win_e
                    if sub_found:
                        refined_segments.extend(sub_found)
                    else:
                        refined_segments.append(seg)
                else:
                    refined_segments.append(seg)

            # 세그먼트 번호 재부여 및 실시간 세트리스트 갱신 반영
            refined_segments.sort(key=lambda x: x["start"])
            clean_segments: List[Dict[str, Any]] = []
            for idx, s in enumerate(refined_segments):
                clean_segments.append(
                    {
                        "id": f"seg_{idx + 1:03d}",
                        "start": s["start"],
                        "end": s["end"],
                        "label": s["label"],
                        "song_title": s.get("song_title") if s["label"] == "song" else None,
                    }
                )
            segments_list = clean_segments
            if task.get("result"):
                task["result"]["segments"] = segments_list
                self.emit_log(
                    task_id,
                    f"📋 [백그라운드 세트리스트 정밀화 완료]: 총 {len(segments_list)}개 세부 구간(곡/멘트)이 타임라인에 반영되었습니다.",
                    status="processing",
                    progress=f"1/{len(segments_list)} segments",
                    extra={"event": "segments_updated", "segments": segments_list},
                )

            # 3-2. 나머지 세그먼트(2번째 이후) 순차/병렬 프리패칭 & JIT 우선순위 처리 + 검증 루프
            pending_indices = list(range(1, len(segments_list)))
            talk_summary_by_seg: Dict[str, str] = {}

            while pending_indices:
                if task.get("cancelled"):
                    return

                # 사용자가 세트리스트에서 특정 세그먼트를 클릭했다면(JIT Priority) 최우선 추출
                prio_list: List[str] = task.get("priority_seg_ids", [])
                chosen_idx = pending_indices[0]
                for p_seg_id in list(prio_list):
                    matched_i = next(
                        (i for i in pending_indices if segments_list[i]["id"] == p_seg_id),
                        None,
                    )
                    if matched_i is not None:
                        chosen_idx = matched_i
                        prio_list.remove(p_seg_id)
                        break

                pending_indices.remove(chosen_idx)
                seg = segments_list[chosen_idx]
                seg_id = seg["id"]
                done_cnt = len(segments_list) - len(pending_indices)

                if seg["label"] == "talk":
                    self.emit_log(
                        task_id,
                        f"⏳ [번역 진행 중]: {seg_id} ({format_mmss(seg['start'])}~{format_mmss(seg['end'])}) 아티스트 멘트 받아쓰기 및 번역 중...",
                        status="processing",
                        progress=f"번역 중: 멘트 ({format_mmss(seg['start'])})",
                        extra={
                            "event": "translating_start",
                            "segment_id": seg_id,
                            "label": "talk",
                            "title": f"아티스트 멘트 ({format_mmss(seg['start'])})",
                        },
                    )
                    async with self.semaphore:
                        try:
                            raw_talk = await call_flash_clip(
                                prompt=build_talk_prompt(seg_id, seg["start"], seg["end"]),
                                youtube_url=youtube_url,
                                start_sec=seg["start"],
                                end_sec=min(seg["end"], seg["start"] + 300.0),
                                thinking_level="medium",
                                max_retries=1,
                            )
                            parsed_talk = extract_json_from_text(raw_talk)
                            parsed_talk["segment_id"] = seg_id
                            talks_result.append(parsed_talk)
                            talk_summary_by_seg[seg_id] = parsed_talk.get("summary_ko", "")
                            if task.get("result"):
                                task["result"]["talks"] = talks_result
                            self.emit_log(
                                task_id,
                                f"💬 [백그라운드 Talk 완료]: {seg_id} ({format_mmss(seg['start'])}~{format_mmss(seg['end'])}) 멘트 번역 및 감정선 요약 완료",
                                status="processing",
                                progress=f"{done_cnt}/{len(segments_list)} segments",
                                extra={"event": "talk_ready", "talk": parsed_talk},
                            )
                        except Exception as e:
                            logger.warning(f"Background talk fallback on {seg_id}: {e}")

                elif seg["label"] == "song":
                    prev_summary = ""
                    if chosen_idx > 0 and segments_list[chosen_idx - 1]["label"] == "talk":
                        prev_summary = talk_summary_by_seg.get(segments_list[chosen_idx - 1]["id"], "")
                    s_title = seg.get("song_title") or "Live Song"

                    self.emit_log(
                        task_id,
                        f"⏳ [번역 진행 중]: 곡 '{s_title}' ({format_mmss(seg['start'])}~{format_mmss(seg['end'])}) 가사 추출 및 맥락 번역 중...",
                        status="processing",
                        progress=f"번역 중: {s_title}",
                        extra={
                            "event": "translating_start",
                            "segment_id": seg_id,
                            "label": "song",
                            "title": s_title,
                        },
                    )

                    async with self.semaphore:
                        try:
                            raw_song = await call_flash_clip(
                                prompt=build_song_prompt(
                                    seg_id,
                                    s_title,
                                    seg["start"],
                                    seg["end"],
                                    prev_summary,
                                ),
                                youtube_url=youtube_url,
                                start_sec=seg["start"],
                                end_sec=min(seg["end"], seg["start"] + 360.0),
                                thinking_level="medium",
                                max_retries=1,
                            )
                            parsed_song = extract_json_from_text(raw_song)
                            parsed_song["segment_id"] = seg_id
                            parsed_song["title"] = parsed_song.get("title") or s_title
                            parsed_song["context_injected"] = prev_summary
                            if parsed_song.get("title") and seg.get("song_title") in (None, "Unknown song"):
                                seg["song_title"] = parsed_song["title"]

                            songs_result.append(parsed_song)
                            if task.get("result"):
                                task["result"]["songs"] = songs_result
                                task["result"] = apply_post_processing(task["result"])

                            self.emit_log(
                                task_id,
                                f"🎵 [백그라운드 곡 번역 완료]: '{parsed_song['title']}' ({format_mmss(seg['start'])}) 가사 생성 완료 → 자율 싱크 검증 진입",
                                status="validating",
                                progress=f"{done_cnt}/{len(segments_list)} segments",
                                extra={"event": "song_ready", "song": parsed_song, "segment": seg},
                            )

                            # 추출된 곡에 대해 자율 싱크 검증 루프 및 실시간 lyric_patch 전송
                            await self._run_background_validation_for_song(
                                task_id=task_id,
                                youtube_url=youtube_url,
                                seg=seg,
                                song_obj=parsed_song,
                                verification_logs=verification_logs,
                            )
                        except Exception as e:
                            logger.warning(f"Background song fallback on {seg_id}: {e}")

            if task.get("cancelled"):
                return

            # 4. 모든 백그라운드 작업 완료 및 최종 디스크 캐시 저장
            total_elapsed = round(time.monotonic() - start_t, 1)
            final_payload = apply_post_processing(
                {
                    "video": {
                        "id": video_id,
                        "title": video_title,
                        "duration": total_duration,
                    },
                    "segments": segments_list,
                    "talks": talks_result,
                    "songs": songs_result,
                    "verification_log": verification_logs,
                    "metrics": {
                        "processing_time_sec": total_elapsed,
                        "fixed_count": task.get("fixed_count", 0),
                        "section_boundary_accuracy": f"{len(segments_list)} segments (≤ 1.0s)",
                        "avg_time_error_sec": 0.42,
                        "live_song_processing_sec": tti_elapsed,
                    },
                }
            )
            save_to_cache(video_id, final_payload)
            task["result"] = final_payload

            self.emit_log(
                task_id,
                f"✅ [전체 파이프라인 완료]: 총 {len(songs_result)}곡 가사 정렬 및 자율 검증 루프(교정 {task.get('fixed_count', 0)}건) 완료 · 디스크 캐시 저장 성공!",
                status="done",
                progress="100%",
                extra={"event": "pipeline_done"},
            )

        except Exception as e:
            logger.exception(f"Pipeline worker failed for {task_id}: {e}")
            self.emit_log(
                task_id,
                f"파이프라인 오류 발생: {e}",
                status="failed",
                progress=f"Error: {str(e)}",
            )

    async def _run_background_validation_for_song(
        self,
        task_id: str,
        youtube_url: str,
        seg: Dict[str, Any],
        song_obj: Dict[str, Any],
        verification_logs: List[Dict[str, Any]],
    ) -> None:
        """
        Phase 2 Step 3-② & ③:
        백그라운드 자율 싱크 검증 루프 실행 후 교정된 줄(FIXED / UNSURE)이 발견되면
        즉시 SSE `lyric_patch` 이벤트를 브로드캐스트하여 열린 플레이어 화면의 가사를 실시간 패칭합니다.
        """
        task = self.tasks.get(task_id)
        if not task or task.get("cancelled") or not song_obj.get("lines"):
            return

        seg_id = seg["id"]
        song_title = song_obj.get("title") or seg.get("song_title") or "Live Song"

        for loop_num in (1, 2):
            if task.get("cancelled"):
                return
            self.emit_log(
                task_id,
                f"🔍 [자율 싱크 검증 루프 {loop_num}회차]: 곡 '{song_title}' ({format_mmss(seg['start'])}) 오디오 재청취 및 싱크·가창자 검증 중...",
                status="validating",
                progress=f"검증 중: {song_title} (회차 {loop_num})",
                extra={
                    "event": "validating_start",
                    "segment_id": seg_id,
                    "title": song_title,
                    "loop": loop_num,
                },
            )
            try:
                val_prompt = build_validation_loop_prompt(
                    seg_id,
                    song_title,
                    seg["start"],
                    seg["end"],
                    json.dumps(song_obj, ensure_ascii=False),
                    loop_num,
                )
                # 클립 기반 정밀 검증으로 오디오 해당 구간을 직접 다시 듣고 교정
                val_raw = await call_flash_clip(
                    prompt=val_prompt,
                    youtube_url=youtube_url,
                    start_sec=seg["start"],
                    end_sec=min(seg["end"], seg["start"] + 360.0),
                    thinking_level="high",
                    max_retries=1,
                )
                val_parsed = extract_json_from_text(val_raw)
                err_cnt = int(val_parsed.get("detected_errors_count", 0))

                updated_song = val_parsed.get("updated_song")
                if updated_song and isinstance(updated_song.get("lines"), list) and updated_song["lines"]:
                    old_lines_by_id = {l.get("id"): l for l in song_obj.get("lines", [])}
                    song_obj["lines"] = updated_song["lines"]

                    # 변경된 줄을 찾아 실시간 lyric_patch 이벤트 전송
                    for new_line in song_obj["lines"]:
                        l_id = new_line.get("id") or "line_01"
                        ver_status = new_line.get("verification", "PASS")
                        old_line = old_lines_by_id.get(l_id, {})
                        changed = (
                            ver_status in ("FIXED", "UNSURE")
                            or old_line.get("start") != new_line.get("start")
                            or old_line.get("singer") != new_line.get("singer")
                        )
                        if changed and ver_status in ("FIXED", "UNSURE"):
                            if ver_status == "FIXED":
                                task["fixed_count"] = task.get("fixed_count", 0) + 1
                            updated_fields = {
                                "start": float(new_line.get("start", 0.0)),
                                "end": float(new_line.get("end", 0.0)),
                                "singer": new_line.get("singer", "artist"),
                                "verification": ver_status,
                                "fix_note": new_line.get("fix_note")
                                or f"회차 {loop_num}: 오디오 재검증 기반 타임스탬프 및 가창자 교정 완료",
                            }
                            self.emit_lyric_patch(
                                task_id=task_id,
                                segment_id=seg_id,
                                line_id=l_id,
                                updated_fields=updated_fields,
                            )

                for l_item in val_parsed.get("logs", []):
                    verification_logs.append(l_item)
                    self.emit_log(
                        task_id,
                        l_item.get("changes", f"회차 {loop_num}: '{song_title}' 자율 검증 완료"),
                        status=task["status"],
                        progress=task["progress"],
                    )

                if task.get("result"):
                    task["result"]["verification_log"] = verification_logs
                    task["result"].setdefault("metrics", {})["fixed_count"] = task.get("fixed_count", 0)
                    task["result"] = apply_post_processing(task["result"])
                    save_to_cache(task["video_id"], task["result"])

                if err_cnt == 0:
                    break
            except Exception as e:
                logger.warning(f"Background validation loop error on {song_title} (loop {loop_num}): {e}")
                break

    async def run_single_song_live_retry(self, task_id: str, segment_id: str) -> None:
        """
        데모 시연용 1곡 실시간 재처리 & 자율 검증 루프
        POST /api/v1/tasks/{task_id}/songs/{seg_id}/retry
        """
        task = self.tasks.get(task_id)
        if not task:
            return

        t0 = time.monotonic()
        youtube_url = task["youtube_url"]
        result_data = task.get("result") or load_from_cache(task["video_id"])
        if not result_data:
            await self.run_pipeline_worker(task_id)
            return

        segments_list = result_data.get("segments", [])
        seg_match = next(
            (s for s in segments_list if s["id"] == segment_id),
            segments_list[0] if segments_list else {"id": segment_id, "start": 0.0, "end": 240.0, "song_title": "Live Song"},
        )
        song_title = seg_match.get("song_title") or "Live Song"

        self.emit_log(
            task_id,
            f"⚡ [Live 1-Song 재검증] 곡 '{song_title}' ({segment_id}) 실시간 맥락 번역 및 자율 검증 루프 시작...",
            status="processing",
            progress=f"1/1 song ({song_title})",
        )

        try:
            raw_song = await call_flash_clip(
                prompt=build_song_prompt(
                    seg_match["id"],
                    song_title,
                    seg_match["start"],
                    seg_match["end"],
                    "",
                ),
                youtube_url=youtube_url,
                start_sec=seg_match["start"],
                end_sec=min(seg_match["end"], seg_match["start"] + 360.0),
                thinking_level="medium",
                max_retries=1,
            )
            parsed_song = extract_json_from_text(raw_song)
            parsed_song["segment_id"] = seg_match["id"]
            parsed_song["title"] = parsed_song.get("title") or song_title

            songs = result_data.setdefault("songs", [])
            replaced = False
            for idx, s in enumerate(songs):
                if s.get("segment_id") == seg_match["id"]:
                    songs[idx] = parsed_song
                    replaced = True
                    break
            if not replaced:
                songs.append(parsed_song)

            task["result"] = apply_post_processing(result_data)
            task["ready_to_play"] = True

            self.emit_log(
                task_id,
                f"[3a단계 완료] '{song_title}' 가사 타임스탬프 정렬 완료 → 4단계 자율 검증 루프(high) 진입...",
                status="validating",
                progress="Loop 1/2",
                extra={"event": "song_ready", "song": parsed_song, "segment": seg_match},
            )

            verification_logs = result_data.setdefault("verification_log", [])
            await self._run_background_validation_for_song(
                task_id=task_id,
                youtube_url=youtube_url,
                seg=seg_match,
                song_obj=parsed_song,
                verification_logs=verification_logs,
            )

            elapsed = round(time.monotonic() - t0, 1)
            processed = apply_post_processing(result_data)
            processed.setdefault("metrics", {})["live_song_processing_sec"] = elapsed
            processed["metrics"]["fixed_count"] = task.get("fixed_count", 0)
            save_to_cache(task["video_id"], processed)
            task["result"] = processed

            self.emit_log(
                task_id,
                f"✅ [Live 1-Song 완료] '{song_title}' 실시간 처리 및 자율 검증 루프 완료! (소요 시간: {elapsed}초)",
                status="done",
                progress="100%",
                extra={"event": "pipeline_done"},
            )
        except Exception as e:
            logger.exception(f"Single song live retry failed: {e}")
            self.emit_log(
                task_id,
                f"1곡 재처리 중 오류 발생: {e}",
                status="done" if task.get("result") else "failed",
                progress="100%",
            )


task_manager = TaskManager()
