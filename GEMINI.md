# Antigravity Workspace Rules & Coding Guidelines

## 🚫 절대 금지 사항 (Strict Prohibitions)

Antigravity 에이전트는 계획 수립, 도구 실행, 코드 작성 시 아래 4가지 항목을 어떠한 경우에도 포함하거나 실행하지 마십시오. 위반 시 즉시 중단하고 대안을 제시해야 합니다.

1. **유튜브 다운로드 도구 및 코드 사용 금지**:
   - `yt-dlp`, `pytube`, `youtube-dl` 등 로컬 서버로 유튜브 영상을 다운로드하거나 오디오를 추출/변환하는 라이브러리 및 코드 작성을 엄격히 금지합니다.
   - 모든 영상 재생은 프론트엔드의 **YouTube IFrame Player API** 임베드 방식만 사용하며, API 입력은 YouTube URL 자체를 전달합니다.

2. **Deprecated API 파라미터 사용 금지**:
   - Google GenAI SDK 및 Gemini 4 Argon 호출 시 구버전/폐기된 파라미터인 `temperature`, `top_p`, `top_k`, `thinking_budget`, `cached_content`를 코드에 작성하지 마십시오.
   - 공식 Interactions API (`client.interactions.create`, `generation_config={"thinking_level": "..."}`) 규격만 준수하십시오.

3. **프론트엔드 내 API 키 노출 금지**:
   - `static/index.html` 및 클라이언트 JavaScript 코드에 `GEMINI_API_KEY`를 절대 하드코딩하거나 노출하지 마십시오.
   - API 키는 오직 백엔드 `.env` 파일에 보관되며, 모든 AI 호출은 FastAPI 엔드포인트를 통해서만 수행됩니다.

4. **React, Vite, Webpack 등 프론트엔드 빌드 도구 도입 금지**:
   - 본 프로젝트의 프론트엔드는 **단일 `static/index.html` (Vanilla JS / CSS3 / HTML5)** 아키텍처를 영구 유지합니다.
   - React, Vue, Vite, 번들러 셋업이나 별도 빌드 스크립트를 추가하지 마십시오.

---

## 🛠️ 개발 및 응답 원칙 (Development Principles)

- **문서 및 주석 보존**: 기존의 기획 문서, 주석, docstring을 임의로 삭제하지 말고 정합성을 유지하십시오.
- **클릭 가능한 파일 링크**: 파일이나 경로를 언급할 때는 `[filename](file:///path/to/file)` 형식의 클릭 가능한 링크를 제공하십시오.
- **단일 페이지 SPA 무결성**: UI 수정 시 `static/index.html` 내에서 스타일과 스크립트가 온전히 동작하도록 유지하십시오.
