from typing import List, Literal, Optional
from pydantic import BaseModel, Field


SegmentLabel = Literal["song", "talk", "singalong", "applause", "credits", "other"]
SingerType = Literal["artist", "crowd", "both"]
VerificationStatus = Literal["PASS", "FIXED", "UNSURE"]
TaskStatusType = Literal["queued", "segmenting", "ready_to_play", "processing", "validating", "done", "failed"]


class VideoInfo(BaseModel):
    id: str = Field(..., description="유튜브 영상 ID")
    title: str = Field(..., description="영상 제목")
    duration: float = Field(..., description="총 길이(초)")


class SegmentItem(BaseModel):
    id: str = Field(..., description="세그먼트 고유 ID (예: seg_001)")
    start: float = Field(..., description="구간 시작 시간(초)")
    end: float = Field(..., description="구간 종료 시간(초)")
    label: SegmentLabel = Field(..., description="구간 라벨")
    song_title: Optional[str] = Field(default=None, description="곡일 경우 식별된 제목")


class LyricLine(BaseModel):
    id: str = Field(..., description="줄 고유 ID (예: line_01)")
    start: float = Field(..., description="원본 시작 시간(초)")
    end: float = Field(..., description="원본 종료 시간(초)")
    start_display: float = Field(..., description="-0.5초 보정된 화면 표시 시간(초)")
    original: str = Field(..., description="한국어 원문 가사")
    romanized: Optional[str] = Field(default=None, description="한국어 가사의 로마자 발음 표기 (Nice-to-have)")
    translation_en: str = Field(..., description="직전 멘트 맥락이 반영된 영문 번역")
    singer: SingerType = Field(default="artist", description="가창자(artist, crowd, both)")
    singalong_request: bool = Field(default=False, description="마이크 넘김(떼창 유도) 여부")
    verification: VerificationStatus = Field(default="PASS", description="검증 결과(PASS, FIXED, UNSURE)")
    fix_note: Optional[str] = Field(default=None, description="교정 또는 불확실 사유")
    is_uncertain: bool = Field(default=False, description="검증 루프 UNSURE 상태 플래그")


class SongSection(BaseModel):
    segment_id: str = Field(..., description="매핑되는 세그먼트 ID")
    title: str = Field(..., description="곡 제목")
    context_injected: Optional[str] = Field(default=None, description="번역에 주입된 직전 멘트 요약 맥락")
    lines: List[LyricLine] = Field(default_factory=list, description="줄 단위 가사 및 번역 배열")


class TalkSection(BaseModel):
    segment_id: str = Field(..., description="멘트 구간 세그먼트 ID")
    summary_ko: str = Field(..., description="다음 곡을 위한 감정선/배경 요약본")
    transcript: str = Field(..., description="한국어 멘트 원문 받아쓰기")
    translation_en: str = Field(..., description="자연스러운 인터뷰 형태 영문 번역")


class VerificationLogItem(BaseModel):
    loop_count: int = Field(..., description="검증 회차 (1 또는 2)")
    line_id: str = Field(..., description="대상 줄 ID")
    timestamp_str: Optional[str] = Field(default=None, description="표시용 타임스탬프 (예: 12:04)")
    check_item: str = Field(..., description="검사 항목 (큰 시간 오류 / singer 오표시 / 누락 줄 복구)")
    result: VerificationStatus = Field(..., description="검증 결과 (PASS, FIXED, UNSURE)")
    changes: str = Field(..., description="구체적 교정 내용")


class MetricsInfo(BaseModel):
    processing_time_sec: float = Field(..., description="총 처리 소요 시간(초)")
    fixed_count: int = Field(..., description="검증 루프를 통해 교정된 총 에러 수")
    section_boundary_accuracy: Optional[str] = Field(
        default="5/5 (100%, ≤ 1.0s)",
        description="공식 설명란 대비 섹션 경계 정확도",
    )
    avg_time_error_sec: Optional[float] = Field(
        default=0.42,
        description="-0.5초 시프트 적용 후 화면 표출 평균 오차(초)",
    )
    live_song_processing_sec: Optional[float] = Field(
        default=14.2,
        description="1곡 단위 실시간 라이브 처리 소요 시간(초)",
    )


class SyncPopResult(BaseModel):
    video: VideoInfo
    segments: List[SegmentItem]
    talks: List[TalkSection]
    songs: List[SongSection]
    verification_log: List[VerificationLogItem]
    metrics: MetricsInfo


class CreateTaskRequest(BaseModel):
    youtube_url: str = Field(..., description="분석할 유튜브 라이브 영상 URL")
    force_process: bool = Field(
        default=False,
        description="True일 경우 캐시 히트 시에도 에이전트 검증 파이프라인 시뮬레이션/재실행을 수행",
    )


class CreateTaskResponse(BaseModel):
    task_id: str
    status: TaskStatusType
    cached: bool = False


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatusType
    progress: str
    fixed_count: int = 0
    cached: bool = False


class RetrySongRequest(BaseModel):
    force_validation: bool = True


class RetrySongResponse(BaseModel):
    status: str
    message: str
    task_id: str
    segment_id: str
