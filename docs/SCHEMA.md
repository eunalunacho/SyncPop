# SCHEMA.md

## 1. 결과 JSON 스키마 명세 및 예시

### 데이터 스키마 구조

| 최상위 필드 | 하위 필드 | 타입 | 설명 |
| --- | --- | --- | --- |
| **video** | `id`, `title`, `duration` | String, String, Number | 유튜브 영상 ID, 영상 제목, 총 길이(초) |
| **segments** | `id`, `start`, `end`, `label`, `song_title` | String, Number, Number, String, String(Null) | 전체 구간 라벨(`song`, `talk`, `singalong`, `applause`, `credits`, `other`). 곡일 경우 식별된 제목 포함. |
| **songs** | `segment_id`, `title`, `lines[]` | String, String, Array | 곡 단위 처리 결과 및 가사 배열 |
| ↳ **lines** | `id`, `start`, `end`, `start_display` | String, Number, Number, Number | 줄 고유 ID, 원본 시작(초), 종료(초), -0.5초 보정된 화면 표시 시간 |
| | `original`, `translation_en` | String, String | 한국어 원문 가사, 맥락이 반영된 영문 번역 |
| | `singer`, `singalong_request` | String, Boolean | 가창자(`artist`, `crowd`, `both`), 마이크 넘김 여부 |
| | `verification`, `fix_note` | String, String(Null) | 검증 결과(`PASS`, `FIXED`, `UNSURE`), 교정 사유 |
| **talks** | `segment_id`, `summary_ko`, `transcript`, `translation_en` | String, String, String, String | 멘트 구간 ID, 다음 곡을 위한 요약본, 원문, 영문 번역 |
| **verification_log** | `loop_count`, `line_id`, `check_item`, `result`, `changes` | Number, String, String, String, String | 검증 회차, 대상 줄 ID, 검사 항목(시간/가창자/누락), 결과, 구체적 교정 내용 |
| **metrics** | `processing_time_sec`, `fixed_count` | Number, Number | 총 처리 소요 시간(초), 루프를 통해 교정된 총 에러 수 |

---

### 최종 결과 JSON 예시

```json
{
  "video": {
    "id": "38HUU-GIVmA",
    "title": "선우정아 미니콘서트 Full Version Film",
    "duration": 4986.0
  },
  "segments": [
    {
      "id": "seg_001",
      "start": 120.0,
      "end": 150.0,
      "label": "talk",
      "song_title": null
    },
    {
      "id": "seg_002",
      "start": 150.0,
      "end": 350.0,
      "label": "song",
      "song_title": "가상의 곡"
    }
  ],
  "talks": [
    {
      "segment_id": "seg_001",
      "summary_ko": "가장 힘들 때 쓴 곡이라며 관객에게 함께 불러달라고 요청함.",
      "transcript": "이 곡은 제가 가장 힘들 때 썼던 곡이에요. 같이 불러주세요.",
      "translation_en": "I wrote this song when I was having the hardest time. Please sing along with me."
    }
  ],
  "songs": [
    {
      "segment_id": "seg_002",
      "title": "가상의 곡",
      "lines": [
        {
          "id": "line_01",
          "start": 155.0,
          "end": 158.0,
          "start_display": 154.5,
          "original": "너와 함께한 시간",
          "translation_en": "The time I spent with you",
          "singer": "artist",
          "singalong_request": false,
          "verification": "PASS",
          "fix_note": null
        },
        {
          "id": "line_02",
          "start": 159.0,
          "end": 162.0,
          "start_display": 158.5,
          "original": "기억해",
          "translation_en": "I remember",
          "singer": "artist",
          "singalong_request": true,
          "verification": "PASS",
          "fix_note": null
        },
        {
          "id": "line_03",
          "start": 163.5,
          "end": 166.0,
          "start_display": 163.0,
          "original": "영원히",
          "translation_en": "Forever",
          "singer": "crowd",
          "singalong_request": false,
          "verification": "FIXED",
          "fix_note": "시간 오류: 1.8초 지연 발견 -> 163.5로 수정"
        },
        {
          "id": "line_04",
          "start": 167.0,
          "end": 170.0,
          "start_display": 166.5,
          "original": "고마워",
          "translation_en": "Thank you",
          "singer": "both",
          "singalong_request": false,
          "verification": "UNSURE",
          "fix_note": "가창자 식별 불가: 밴드 소음으로 관객 목소리 명확히 확인 불가"
        }
      ]
    }
  ],
  "verification_log": [
    {
      "loop_count": 1,
      "line_id": "line_03",
      "check_item": "큰 시간 오류",
      "result": "FIXED",
      "changes": "기존 165.3초 -> ±3초 재탐색 후 163.5초로 앞당겨 재정렬"
    },
    {
      "loop_count": 2,
      "line_id": "line_04",
      "check_item": "singer 오표시",
      "result": "UNSURE",
      "changes": "both 라벨 검증(관객 목소리 뚜렷함 여부) -> UNSURE 판단. 기존 유지."
    }
  ],
  "metrics": {
    "processing_time_sec": 485.2,
    "fixed_count": 1
  }
}
```

---

## 2. REST API 명세

| 기능 | 메서드 | 경로 (Endpoint) | 요청 (Request) 예시 | 응답 (Response) 예시 |
| --- | --- | --- | --- | --- |
| **작업 생성** | POST | `/api/v1/tasks` | `{"youtube_url": "https://youtu.be/38HUU-GIVmA"}` | `{"task_id": "yt_38HUU_v1", "status": "queued"}` |
| **상태 조회** | GET | `/api/v1/tasks/{task_id}/status` | *(경로 파라미터)* | `{"status": "processing", "progress": "12/23 segments"}` |
| **결과 조회** | GET | `/api/v1/tasks/{task_id}/result` | *(경로 파라미터)* | *(위 1번의 전체 결과 JSON)* |
| **진행 로그** | GET | `/api/v1/tasks/{task_id}/logs` | *(경로 파라미터)* | `data: {"msg": "회차 1: 37:36 구간 재정렬"}\n\n` *(SSE)* |
| **곡 1개 재처리 (데모용)** | POST | `/api/v1/tasks/{task_id}/songs/{seg_id}/retry` | `{"force_validation": true}` | `{"status": "queued", "message": "Demo validation started"}` |

---

## 3. 작업 상태 값 (Task Status) 및 진행률

| 상태 값 | 설명 | 진행률 (Progress) 표시 방법 |
| --- | --- | --- |
| **queued** | 백그라운드 작업 대기 중 | `0%` |
| **segmenting** | 전체 오디오를 1M 컨텍스트로 대분할 중 (약 8분) | `Calculating segments...` |
| **processing** | 분할된 각 곡과 멘트를 병렬 처리 중 (번역/정렬) | 처리 완료 구간 수 / 전체 구간 수 (예: `5/23 segments`) |
| **validating** | Song 구간 대상 자율 싱크 검증 루프 작동 중 | 현재 루프 회차 / 최대 회차 (예: `Loop 1/2`) |
| **done** | 모든 파이프라인 통과 및 캐시 저장 완료 | `100%` |
| **failed** | 재시도 후에도 복구 불가한 에러 발생 | `Error Detail` |

---

## 4. 캐시 키 규칙 (Cache Key Rule)

- **포맷**: `{Video_ID}_{Prompt_Version}`
- **예시**: `yt_38HUU_GIVmA_v1.0`
- **목적**: 동일한 영상이라도 프롬프트 지시어(버전)가 수정되었을 경우 기존 캐시를 무시하고 새로 생성되도록 버저닝 관리 적용. (프롬프트 버전은 백엔드 환경변수에서 관리).

---

## 5. 보안 규칙 (Security Constraints)

| 보안 항목 | 규칙 및 조치 사항 |
| --- | --- |
| **API 키 격리** | `GEMINI_API_KEY`는 Cloud Run 백엔드의 환경변수(Env Vars)에만 존재해야 함. |
| **프론트엔드 차단** | 브라우저 소스코드(HTML, JS), 로컬 스토리지 등에 API 키 절대 노출 금지. 클라이언트는 백엔드의 자체 API(`/api/v1/tasks`)만 호출. |
| **GitHub 관리** | Public Repository 전환 전, `.env` 파일이 커밋되지 않도록 `.gitignore` 필수 점검. 하드코딩 흔적 발견 즉시 실격 처리됨. |
