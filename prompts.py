"""
SyncPop Live - Stage-by-Stage Prompt Definitions for Gemini 4 Argon
Follows PIPELINE.md Section 3 rules strictly.
"""

COMMON_SYSTEM_INSTRUCTION = (
    "실제로 들리고 보이는 것만 근거로 판단하라. "
    "'콘서트에서는 보통 이렇다'는 식의 추측은 엄격히 금지한다. "
    "스튜디오 음원의 가사를 기억해서 쓰지 말고 라이브에서 실제로 부른 대로만 적어라. "
    "판단 근거가 부족하면 임의로 채우지 말고 null 또는 UNSURE를 반환하라. "
    "반드시 유효한 JSON 형식으로만 응답하라."
)


def build_segmentation_prompt(video_title: str = "") -> str:
    """[2단계] 전체 분할 (Segmentation) - thinking_level: low"""
    return f"""[2단계: 전체 라이브 공연 구간 분할]
영상 제목 참고: {video_title or "선우정아 미니콘서트 Full Version Film"}

지시사항:
1. 입력된 라이브 공연 오디오 전체를 듣고 타임라인을 끊김 없이 분할하라.
2. 각 구간을 song, talk, singalong, applause, credits, other 중 하나로 분류하라.
3. 곡 제목(song_title)은 1순위로 화면 내 영상 자막에 의존하되, 자막이 없으면 실제로 부른 가사를 통해 유추하고 확신할 수 없으면 'Unknown song'으로 적어라. (비곡 구간은 null)
4. 출력은 반드시 아래 JSON 배열 스키마만 반환하라:
[
  {{
    "id": "seg_001",
    "start": 0.0,
    "end": 120.0,
    "label": "talk",
    "song_title": null
  }},
  {{
    "id": "seg_002",
    "start": 120.0,
    "end": 350.0,
    "label": "song",
    "song_title": "원해"
  }}
]
"""


def build_talk_prompt(segment_id: str, start: float, end: float) -> str:
    """[3b단계] 멘트 단위 처리 (Talk) - thinking_level: medium"""
    return f"""[3b단계: 아티스트 멘트(Talk) 구간 처리]
대상 구간 ID: {segment_id} ({start:.1f}초 ~ {end:.1f}초)

지시사항:
1. 해당 구간({start:.1f}s ~ {end:.1f}s)에서 가수가 말하는 내용을 실제로 들리는 그대로 정확하게 받아쓰고(transcript), 영어로 자연스럽게 인터뷰 형태로 번역하라(translation_en).
2. 이 멘트에 다음 곡에 대한 감정선이나 배경 설명이 있다면 2~3줄로 요약하여 summary_ko 필드에 담아라.
3. 출력은 반드시 아래 JSON 객체만 반환하라:
{{
  "segment_id": "{segment_id}",
  "summary_ko": "다음 곡을 위한 감정선 및 배경 요약 (2~3줄)",
  "transcript": "한국어 멘트 받아쓰기 원문",
  "translation_en": "Natural English translation of the artist's talk"
}}
"""


def build_song_prompt(
    segment_id: str,
    song_title: str,
    start: float,
    end: float,
    previous_talk_summary: str = "",
) -> str:
    """[3a단계] 곡 단위 처리 (Song) - thinking_level: medium"""
    context_block = (
        previous_talk_summary.strip()
        if previous_talk_summary
        else "직전 멘트 맥락 없음 (곡 자체의 라이브 발성과 감정에 집중하여 번역)"
    )
    return f"""[3a단계: 맥락 기반 곡 단위 처리 및 번역]
대상 구간 ID: {segment_id} ({start:.1f}초 ~ {end:.1f}초)
곡 제목: {song_title}
직전 멘트(talk) 요약 맥락(context): "{context_block}"

지시사항:
1. 제공된 곡 구간({start:.1f}s ~ {end:.1f}s) 오디오의 가사를 들리는 그대로 0.1초 단위의 타임스탬프(start, end)와 함께 줄 단위로 정렬하라. 스튜디오 가사를 외워서 적지 말고 라이브에서 실제 발성한 대로만 기록하라.
2. 영어로 번역할 때(translation_en), 내가 context 변수로 제공한 '직전 멘트(talk)'의 요약을 바탕으로 곡의 감정과 배경을 깊이 있게 반영하라.
3. 한국어 원문 가사(original)와 함께 글로벌 팬을 위한 로마자 발음 표기(romanized)도 함께 생성하라.
4. 가수가 객석으로 마이크를 넘기거나 함께 부르기를 유도하는 순간은 singalong_request를 true로 표기하고, 실제로 관객이 부른 부분은 singer를 "crowd", 가수와 관객이 함께 부른 부분은 "both", 가수 단독은 "artist"로 표기하라.
5. 출력은 반드시 아래 JSON 객체만 반환하라:
{{
  "segment_id": "{segment_id}",
  "title": "{song_title}",
  "lines": [
    {{
      "id": "line_01",
      "start": {start + 5.0:.1f},
      "end": {start + 9.0:.1f},
      "original": "한국어 가사 원문",
      "romanized": "Hangugeo gasa wonmun",
      "translation_en": "Context-infused English lyric translation",
      "singer": "artist",
      "singalong_request": false
    }}
  ]
}}
"""


def build_validation_loop_prompt(
    segment_id: str,
    song_title: str,
    start: float,
    end: float,
    current_song_json: str,
    loop_iteration: int,
) -> str:
    """[4단계] 자율 싱크 검증 루프 (Validation Loop) - thinking_level: high"""
    return f"""[4단계: 자율 싱크 검증 루프 - 회차 {loop_iteration}/2]
대상 곡: {song_title} (구간 {segment_id}: {start:.1f}초 ~ {end:.1f}초)

너는 제공된 가사 JSON과 라이브 오디오가 완벽히 일치하는지 검수하는 품질 관리(QC) 에이전트이다.
실제로 들리는 소리만 근거로 판단하고 추측은 엄격히 금지한다.

[검사 항목 3가지]
1. 큰 시간 오류 (Time Alignment Error):
   - 기준: 줄 시작 시간(start)이 실제 첫 단어 발성 시점과 1.5초 이상 엇나갔는가?
   - 측정 및 수정: 해당 가사 줄의 시작 시간 기준 ±3초 구간의 오디오만 집중해서 다시 듣고, 첫 단어 발성이 시작되는 정확한 시점(0.1초 단위)으로 재정렬하라. 수정한 경우 verification을 "FIXED"로, fix_note에 구체적 사유를 기록하라.

2. 가창자 오표시 (Singer Mislabeling / 환각 방지):
   - 기준: "crowd" 또는 "both"로 라벨링된 줄이 실제로 관객이 부른 것이 맞는가?
   - 측정 및 수정: 해당 구간을 다시 듣고 "이 구간에 관객(다수)의 목소리가 분명하게 들리는가? YES / NO / UNSURE"로만 먼저 자문하라.
     * YES: 기존 crowd/both 라벨 유지 ("PASS")
     * NO: 환각(Hallucination)으로 판단하고 singer를 "artist"로 즉시 교정 ("FIXED", fix_note 기록)
     * UNSURE: 밴드 폭음 등으로 판별 불가 시 verification을 "UNSURE", is_uncertain을 true로 설정하고 fix_note에 사유 기록.

3. 누락 줄 복구 (Omission Check):
   - 기준: 라이브 오디오 상에서 실제로 불렀으나 텍스트 배열에서 빠진 구절이 있는가?
   - 측정 및 수정: 전후 문맥과 오디오를 비교해 비어있는 타임라인에 실제 가창이 있다면 누락된 줄(원문, 로마자, 번역, 타임스탬프)을 삽입하고 verification을 "FIXED"로 표시하라.

검수할 현재 Song JSON:
{current_song_json}

출력은 반드시 아래 JSON 형식으로 반환하라 (detected_errors_count가 0이면 즉시 루프가 종료됨):
{{
  "detected_errors_count": 0,
  "updated_song": {{
    "segment_id": "{segment_id}",
    "title": "{song_title}",
    "lines": [...]
  }},
  "logs": [
    {{
      "loop_count": {loop_iteration},
      "line_id": "line_03",
      "timestamp_str": "12:04",
      "check_item": "큰 시간 오류",
      "result": "FIXED",
      "changes": "회차 {loop_iteration}: 12:04 구간 1.8초 지연 발견 -> ±3초 재탐색 후 시작 시간을 -1.5초 앞당겨 재정렬"
    }}
  ]
}}
"""
