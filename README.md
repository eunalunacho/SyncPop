# 🎵 SyncPop Live

> **Gemini 4 Argon 1M Context Live Concert Lyrics & Sing-Along Player**  
> *Google Gemini Hackathon Submission (Track: Gemini 4 Argon in Entertainment)*

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Google GenAI SDK](https://img.shields.io/badge/AI-Google%20GenAI%20SDK%20(Argon)-4285F4.svg?logo=google&logoColor=white)](https://ai.google.dev)
[![Google Cloud Run](https://img.shields.io/badge/Deploy-Google%20Cloud%20Run-4285F4.svg?logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![Frontend](https://img.shields.io/badge/Frontend-Vanilla%20JS%20%2F%20HTML5-F7DF1E.svg?logo=javascript&logoColor=black)](./static)

---

## 📑 Table of Contents
1. [🌟 Overview](#-overview)
2. [🎯 Problem Statement](#-problem-statement)
3. [✨ Key Features](#-key-features)
4. [🧠 Gemini 4 Argon & Agent Architecture](#-gemini-4-argon--agent-architecture)
5. [🛠️ Tech Stack](#️-tech-stack)
6. [🚀 Quick Start (Local & Docker)](#-quick-start-local--docker)
7. [📂 Project Structure](#-project-structure)
8. [📖 Detailed Documentation](#-detailed-documentation)
9. [🗺️ Roadmap](#️-roadmap)

---

## 🌟 Overview

**SyncPop Live** is an intelligent live concert web player powered by **Gemini 4 Argon**. By utilizing Argon's **1-Million token context window** and **Frontier Reasoning**, SyncPop ingests full 80+ minute concert streams, segments setlists without manual timestamps, contextually infuses artist monologues into lyric translations, and autonomously verifies sing-along moments with self-correcting QC loops.

---

## 🎯 Problem Statement

Global K-pop and K-indie fans watch full concert livestreams on YouTube, but conventional Speech-to-Text (STT) and auto-captioning systems fail in live concert environments:
1. **Phonetic Distortion**: Loud live band sessions and acoustic reverb obscure lyrics.
2. **Disconnected Context**: The emotional background shared by artists during talk segments is lost in lyric translations.
3. **Broken Sing-Alongs**: Audience sing-alongs and microphone handoffs break automated transcription, isolating global fans.

---

## ✨ Key Features

- **1M Context Setlist Segmentation**: Ingests full concert audio in a single pass to automatically detect songs, talks, cheers, and credits.
- **Context-Infused Translation**: Extracts emotional takeaways from preceding artist talks and weaves them into nuanced English lyric translations.
- **Interactive Sing-Along Player**: Detects crowd engagement in real time, triggering animated **"🎤 Sing Along!"** banners and Romanized pronunciations.
- **Autonomous Validation Loop**: Employs `thinking: high` QC agent loops that listen back to $\pm3$s audio snippets, self-correcting hallucinations (e.g., converting false `both` labels to `artist` with `[FIXED]` tags) and fine-tuning timestamps to 0.1s precision.

---

## 🧠 Gemini 4 Argon & Agent Architecture

```
[Full Concert YouTube Stream (80+ min)]
                  │
                  ▼
┌────────────────────────────────────────────────────────┐
│ Stage 1: Full-Stream Setlist Ingestion                 │
│ • Gemini 4 Argon (1M Token Audio Context)              │
│ • thinking: low | Zero-timestamp segmentation         │
└─────────────────────────┬──────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 2: Context-Infused Nuance Alignment              │
│ • GenAI Interactions API (Async 4-Worker Concurrency)   │
│ • thinking: medium | Talk-infused translations         │
└─────────────────────────┬──────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 3: Autonomous QC & Validation Loop               │
│ • Targeted Audio Pinpoint (±3s Window)                │
│ • thinking: high | Self-correcting hallucination fix   │
└─────────────────────────┬──────────────────────────────┘
                          │
                          ▼
[Interactive SyncPop Web Player (Vanilla JS + YouTube IFrame API)]
```

### Thinking Level Strategy
| Stage | Gemini 4 Argon Configuration | Role |
| :--- | :--- | :--- |
| **Setlist Segmentation** | `thinking_level: "low"` | Fast 1M audio ingestion for song/talk boundary detection |
| **Lyric & Translation** | `thinking_level: "medium"` | Accurate 0.1s timestamp alignment & context translation |
| **Validation Loop (QC)** | `thinking_level: "high"` | Deep acoustic reasoning & autonomous error correction |

---

## 🛠️ Tech Stack

- **AI Core**: Google GenAI SDK (`gemini-4-argon`), Interactions API
- **Backend**: FastAPI (Python 3.11+), Async Worker Queue, Server-Sent Events (SSE)
- **Frontend**: Single-Page Application (Vanilla JS / CSS3 / HTML5), YouTube IFrame Player API
- **Infrastructure**: Docker, Google Cloud Run

---

## 🚀 Quick Start (Local & Docker)

### 1. Prerequisites
- Python 3.11+
- Google Gemini API Key with Gemini 4 Argon access

### 2. Local Setup
```bash
# Clone the repository
git clone https://github.com/eunalunacho/SyncPop.git
cd SyncPop

# Create virtual environment & install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your_gemini_api_key_here

# Run development server
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Open [http://localhost:8080](http://localhost:8080) in your browser.

### 3. Docker Run
```bash
docker build -t syncpop-live .
docker run -p 8080:8080 --env-file .env syncpop-live
```

---

## 📂 Project Structure

```
SyncPop/
├── docs/                 # Detailed documentation & PRD/Architecture specs
│   ├── PRD.md            # Product Requirements Document
│   ├── DESIGN.md         # Technical Design & System Architecture
│   ├── PIPELINE.md       # 3-Stage Pipeline & Prompt Specifications
│   ├── RUNBOOK.md        # Local & Cloud Run Deployment Runbook
│   └── SUBMISSION.md     # Hackathon Submission Details & Video Script
├── static/               # Frontend Assets (Vanilla JS / CSS SPA)
│   └── index.html        # Interactive Concert Player Single-Page App
├── cache/                # Pre-processed demo cache files
├── main.py               # FastAPI Application & SSE Endpoints
├── models.py             # Pydantic Schemas & State Models
├── pipeline.py           # Gemini 4 Argon Pipeline & QC Logic
├── prompts.py            # System Prompts & Validation Templates
├── Dockerfile            # Cloud Run Container Definition
├── requirements.txt      # Python Dependencies
├── .env.example          # Sample Environment Configuration
└── README.md             # Project Overview & Quickstart Guide
```

---

## 📖 Detailed Documentation

- [Product Requirements (PRD)](./docs/PRD.md)
- [System Design & Architecture](./docs/DESIGN.md)
- [Pipeline & Prompts Specification](./docs/PIPELINE.md)
- [Deployment Runbook](./docs/RUNBOOK.md)
- [Hackathon Submission Guide](./docs/SUBMISSION.md)

---

## 🗺️ Roadmap

- [x] Full-concert (80+ min) setlist segmentation with 1M token context
- [x] Context-infused song translation reflecting artist talk emotion
- [x] Real-time crowd sing-along detection and player notification
- [x] Autonomous QC validation loop with SSE log streaming
- [ ] Hybrid streaming architecture with sub-15s initial playback
- [ ] Real-time livestream concert synchronization for YouTube/Twitch Live
