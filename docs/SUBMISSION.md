# SyncPop Live - Hackathon Final Submission Guide

> **Track**: Gemini 4 Argon in Entertainment  
> **Tech Stack**: Google GenAI SDK (Gemini 4 Argon), Google Cloud Run, FastAPI, Vanilla JS/HTML5, YouTube IFrame API  
> **Repository**: [Public GitHub Link TBD]  
> **Live Demo**: [Google Cloud Run Deployment URL TBD]  
> **Demo Video**: [YouTube / Google Drive Link TBD]  

---

## 🎬 1. 3-Minute Demo Video Script (3분 데모 영상 대본)

| Time | Visual / Screen | English Narration | 한국어 해석 |
| :--- | :--- | :--- | :--- |
| **0:00 ~ 0:30**<br>(Problem) | **Split Screen / YouTube Comparison**<br>- Left: YouTube's broken auto-captions during Sunwoojunga's live concert (distorted words during band chorus & crowd cheers).<br>- Right: Disconnected subtitles when the artist shares a heartfelt story before the song. | "Global K-pop and K-indie fans watch full concert livestreams, but YouTube's auto-captions fail miserably. In live concerts, loud band instruments distort lyric recognition, audience sing-alongs break transcription entirely, and the artist's emotional talk is never connected to the song's translation. Non-Korean fans feel isolated from the live energy." | "글로벌 K-pop 및 K-인디 팬들이 콘서트 풀버전을 시청할 때 유튜브 자동 자막은 완전히 붕괴됩니다. 라이브에서는 악기 폭음으로 가사가 왜곡되고, 떼창 구간에서는 자막이 끊기며, 아티스트가 전하는 감정선 멘트는 번역에 전혀 반영되지 않습니다. 해외 팬들은 라이브의 열기에서 소외됩니다." |
| **0:30 ~ 1:00**<br>(Segmentation & Setlist) | **SyncPop Live - Main Screen & Setlist Breakdown**<br>- Paste concert YouTube URL.<br>- Instant setlist parsing result displayed on the right drawer.<br>- Show breakdown: [TBD] Songs, [TBD] Talks, [TBD]% section boundary accuracy. | "Enter SyncPop Live. Powered by Gemini 4 Argon's 1-Million token context window, our agent ingests the entire 83-minute live concert in one pass. It automatically segments the timeline into songs, talks, applause, and credits—achieving [TBD]% boundary accuracy with zero manual timestamps." | "SyncPop Live를 소개합니다. Gemini 4 Argon의 100만 토큰 컨텍스트 윈도우를 활용해 83분 콘서트 전체 오디오를 한 번에 이해합니다. 수동 타임스탬프 없이 전체 타임라인을 곡, 멘트, 환호, 크레딧으로 자동 분할하며 [TBD]%의 경계 정확도를 달성했습니다." |
| **1:00 ~ 1:40**<br>(Live Processing & Verification) | **Terminal Screen & Live 1-Song Retry**<br>- Click 'Live Agent Processing' for single song (*Want*).<br>- Progress bar and real-time SSE terminal logs ticking.<br>- Show Loop 1: Detected `both` singer hallucination -> self-corrected to `artist` `[FIXED]`. Time alignment adjusted. (Takes ~14 sec). | "Watch our agent process a song live in just 14 seconds. Notice the autonomous Verification Loop with thinking: high. In Loop 1, Argon listens back to the audio and asks: 'Do we clearly hear audience voices?' Answering NO, it catches the false sing-along hallucination and corrects `both` to `artist` with a [FIXED] tag, while fine-tuning timestamps to 0.1-second precision." | "14초 만에 1곡을 실시간 처리하는 에이전트를 확인해보세요. thinking: high 기반 자율 검증 루프가 작동합니다. 1회차에서 오디오를 다시 듣고 '관객 목소리가 분명히 들리는가?'를 자문한 뒤, NO로 판단하여 가짜 떼창 환각(`both`)을 `artist`로 즉시 교정([FIXED])하고 0.1초 단위로 싱크를 맞춥니다." |
| **1:40 ~ 2:30**<br>(Interactive Player Demo) | **SyncPop Interactive Concert Player**<br>- Smooth karaoke-style lyric sync with Romanization & English.<br>- Show contextual translation infused from previous talk.<br>- Camera pans to crowd: **"🎤 Sing Along!" banner slides in**.<br>- Talk section switches seamlessly to interview-style dialogue. | "In the interactive player, lyrics scroll with 0.1-second synchronization, featuring Romanized pronunciation and deep contextual English translations infused with the artist's preceding monologue. When the artist points the mic to the crowd, the vibrant 'Sing Along!' banner triggers, highlighting crowd lyrics. In talk sections, subtitles naturally shift to interview-style transcripts." | "인터랙티브 플레이어에서는 로마자 발음과 직전 멘트의 감정선이 반영된 심층 영문 번역이 0.1초 단위로 동기화됩니다. 가수가 마이크를 객석으로 넘기면 'Sing Along!' 배너가 등장하여 떼창 파트를 하이라이트합니다. 멘트 구간에서는 인터뷰 형식의 번역으로 매끄럽게 전환됩니다." |
| **2:30 ~ 3:00**<br>(Architecture & What's Next) | **Architecture Diagram & Closing Slide**<br>- 1-page architecture graphic: Gemini 4 Argon (1M Context) + Interactions API + Validation Loop + Google Cloud Run.<br>- Future roadmap: Hybrid Flash chunking & real-time live patching. | "Built entirely on Gemini 4 Argon and deployed on Google Cloud Run, SyncPop transforms passive concert viewing into an immersive, global sing-along experience. Next, we are expanding to live streaming concerts and real-time crowd translation. Thank you." | "Gemini 4 Argon과 Google Cloud Run 위에 구축된 SyncPop은 수동적인 콘서트 시청을 몰입형 글로벌 싱어롱 경험으로 혁신합니다. 다음 단계로 라이브 스트리밍 콘서트 실시간 패칭으로 확장하고자 합니다. 감사합니다." |

---

## 📝 2. English Project Description (300 ~ 500 Words)

### **Title**
**SyncPop Live** — Gemini 4 Argon 1M Context Live Concert Lyrics & Sing-Along Player

### **One-Line Summary**
An intelligent live concert web player powered by Gemini 4 Argon that digests full 83-minute live concert streams, injects artist talk contexts into translations, and autonomously verifies sing-along sync with self-correcting QC loops.

### **Problem**
Over 100 million global fans watch full-length K-pop and K-indie concert streams on YouTube, but existing automatic speech-to-text (STT) and subtitle systems break down in live environments:
1. Acoustic noise from live band sessions causes severe phonetic distortion.
2. Crucial emotional monologues (artist talks) explaining the background of upcoming songs are completely disconnected from lyric translations.
3. Crucial crowd moments—such as when the artist passes the microphone for audience sing-alongs—cut off subtitles completely, isolating global fans from the concert atmosphere.

### **Solution**
SyncPop Live harnesses Gemini 4 Argon's 1-Million token context window and frontier reasoning to deliver an immersive live concert player:
- **Zero-Timestamp Setlist Segmentation**: Automatically splits full 80+ minute concerts into seamless songs, talks, applause, and credits.
- **Context-Infused Translation**: Extracts emotional takeaways from artist talks and injects them into subsequent song lyric translations.
- **Interactive Sing-Along & Romanization**: Detects crowd engagement moments in real time, triggering animated "🎤 Sing Along!" banners and Romanized lyrics for international fans.

### **How It Uses Gemini 4 Argon & Verification Loop**
- **1M Multimodal Audio Context (`thinking: low`)**: Ingests full concert audio in a single interaction to construct comprehensive setlist timelines without manual editing.
- **Context-Infused Lyric Alignment (`thinking: medium`)**: Uses GenAI Interactions API with 4 parallel workers to generate 0.1s timestamped lyrics and nuance-aware translations.
- **Autonomous Validation Loop (`thinking: high`)**: An integrated Quality Control (QC) agent listens back to pinpoint ±3s audio windows and runs targeted objective verification (e.g., *"Are audience voices clearly audible? YES/NO/UNSURE"*), autonomously eliminating singer hallucinations (e.g., converting false `both` labels to `artist` with `[FIXED]` tags) and correcting timing delays.

### **Architecture & Tech Stack**
- **AI Core**: Google GenAI SDK (`gemini-4-argon`), Interactions API (background async polling, zero deprecated parameters).
- **Backend**: FastAPI (Python 3.11+), Async Worker Queue with concurrency control (limit: 4), Server-Sent Events (SSE) for real-time validation logs.
- **Frontend**: Single-Page Application (Vanilla JS / CSS3 / HTML5), YouTube IFrame API two-way time sync, Accessible Dark Mode UI.
- **Cloud Infrastructure**: Containerized with Docker, deployed on **Google Cloud Run**.

### **Results (Metrics)**
- **Section Boundary Accuracy**: `[TBD]` (Measured against official concert timestamps, within $\le$ 1.0s).
- **Average Time Alignment Error**: `[TBD]` seconds.
- **Autonomous Fix Count**: `[TBD]` detected & self-corrected hallucinations via Validation Loop.
- **Live Song Processing Speed**: `[TBD]` seconds per song.

### **What's Next**
- **Hybrid Streaming Architecture**: Sub-15s Time-to-Interactive using Gemini 2.5 Flash parallel chunking and live background QC patching over WebSocket/SSE.
- **Real-Time Livestream Ingestion**: Expanding from on-demand VODs to live YouTube/Twitch broadcast streams with real-time fan cheer sync.

---

## 📂 3. GitHub README.md Table of Contents (목차)

```markdown
# 🎵 SyncPop Live
> Gemini 4 Argon 1M Context Live Concert Lyrics & Sing-Along Player

## 📑 Table of Contents
1. 🌟 Overview & Demo Video
2. 🎯 Problem Statement & Target User
3. ✨ Key Features
   - 1M Context Setlist Segmentation
   - Context-Infused Nuance Translation
   - Real-Time "Sing-Along!" Crowd Detection
   - Autonomous Self-Correcting QC Loop
4. 🧠 Gemini 4 Argon & Agent Architecture
   - Stage-by-Stage Pipeline Flow
   - Thinking Level Strategy (Low / Medium / High)
   - Autonomous Validation Logic
5. 📊 Evaluation & Benchmark Metrics
6. 🛠️ Tech Stack & Google Cloud Deployment
7. 🚀 Getting Started (Local Run & Docker)
8. 🗺️ Roadmap & Phase 2 Plans
9. 📜 License & Acknowledgments
```
