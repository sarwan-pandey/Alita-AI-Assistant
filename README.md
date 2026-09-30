# ⚡ MJ AI Assistant

<p align="center">
  <img src="https://img.shields.io/badge/Status-Production--Ready-00F5FF?style=for-the-badge&logo=statuspage&logoColor=black" alt="Status" />
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18.3-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/Three.js-R170-black?style=for-the-badge&logo=threedotjs&logoColor=white" alt="Three.js" />
  <img src="https://img.shields.io/badge/TTS-Chatterbox--Turbo-FF007F?style=for-the-badge&logo=soundcharts&logoColor=white" alt="Chatterbox Turbo" />
  <img src="https://img.shields.io/badge/CUDA-12.1-76B900?style=for-the-badge&logo=nvidia&logoColor=black" alt="CUDA" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License" />
</p>

<h3 align="center">
  A State-of-the-Art Emotionally Intelligent AGI Assistant, Autonomous Desktop & Mobile Screen Agent, and 3D Living Human Companion.
</h3>

<p align="center">
  <b>Local-First • Ultra-Low Latency • Hardware-Optimized (&lt;4 GB VRAM) • Full Android Bridge</b>
</p>

<p align="center">
  <a href="#-overview"><b>Overview</b></a> •
  <a href="#-key-highlights--capabilities"><b>Key Features</b></a> •
  <a href="#-repository-architecture"><b>Architecture</b></a> •
  <a href="#-quick-start--deployment"><b>Quick Start</b></a> •
  <a href="#-hardware--vram-benchmark"><b>VRAM Budget</b></a> •
  <a href="#-comprehensive-verification--test-suite"><b>Test Suite</b></a> •
  <a href="#-security--privacy"><b>Security</b></a>
</p>

---

## 🌟 Overview

**MJ** (formerly Alita / Aura) is an advanced, autonomous multimodal AI companion engineered to run locally on consumer-grade hardware. Combining ultra-expressive real-time neural speech synthesis, cognitive emotional intelligence, computer-vision desktop screen automation, and a native Android accessibility bridge, MJ acts as a true zero-touch personal operating system and digital companion.

```
       ┌─────────────────────────────────────────────────────────────┐
       │                     USER MULTIMODAL INPUT                    │
       │   🎤 Microphone Audio (16kHz PCM)   │   📱 Android Telemetry │
       │   👁️ Desktop Screen Capture (OCR)   │   ⌨️ Global Hotkeys    │
       └──────────────────────────────┬──────────────────────────────┘
                                      │
                                      ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │                      COGNITIVE BACKEND CORE                       │
    │  • Speech-to-Text: Faster-Whisper (Zero-drop streaming audio)     │
    │  • Decision Router: Deterministic intent & tool classification   │
    │  • Cognitive Brain: Ollama Qwen3:4B (Pinned in-memory / instant)  │
    │  • Memory Pipeline: ChromaDB RAG + SQLite Episodic + KG Graph    │
    │  • Security Guard: Thread-safe high-priority kill switch (STOP)   │
    └─────────────────┬───────────────────────────────┬─────────────────┘
                      │                               │
                      ▼                               ▼
    ┌───────────────────────────────────┐ ┌─────────────────────────────┐
    │     AUTONOMOUS AGENTIC LAYER      │ │    EXPRESSIVE AUDIO & 3D    │
    │ • Desktop Screen Agent (UIA, OCR) │ │ • Sole TTS: Chatterbox      │
    │ • App, Media & Filesystem Control │ │   Turbo (Expressive tags:   │
    │ • Android Phone Bridge Service    │ │   [laugh], [sigh], [cough]) │
    │   (Remote touch, WhatsApp, SMS)   │ │ • 3D Living Avatar (Visemes,│
    │ • Compound Multi-Step Workflows   │ │   blinking, emotions) @60FPS│
    └───────────────────────────────────┘ └─────────────────────────────┘
```

---

## 🚀 Key Highlights & Capabilities

### 🎙️ 1. Chatterbox Turbo Neural Speech (Unified Architecture)
* **Single High-Performance Engine**: Powered exclusively by **Chatterbox-Turbo (350M)**. All text—English, Hindi, Latin-script Hinglish, and mixed code-switched technical vocabulary—is synthesized through one unified neural model.
* **Native Paralinguistic Expression**: Supports conversational human tags `[laugh]`, `[sigh]`, `[cough]` directly inline.
* **Ultra-Low Latency**: Generates natural speech in &lt;300ms, completely replacing legacy multi-engine fallback chains.

### 🎭 2. 3D Living Human Avatar (`frontend-avatar/` — Port 5174)
* **Real-Time Viseme Lip Sync**: Dynamic phoneme-to-morph-target streaming matching Chatterbox Turbo speech output.
* **Biological Micro-Animations**: Procedural natural blinking, micro-saccades, breathing oscillation, and head tracking damped towards cursor/camera.
* **Studio Visuals**: Three.js R3F with studio HDRI environment reflections, bloom postprocessing, and glassmorphic telemetry cards.

### 🖥️ 3. Autonomous Desktop & Screen Agent
* **Computer Vision & OCR**: Inspects active windows, parses UI elements, and binds semantic targets to clickable coordinates.
* **Deterministic Automation**: Opens applications, controls media players, conducts web searches, manages files, and coordinates complex multi-app tasks.
* **Global Barge-in Kill Switch**: Thread-safe high-priority interrupt handler instantly halts runaway automation if the user presses `Esc` or commands *"STOP"*.

### 📱 4. Native Android Companion Bridge (`android_companion/`)
* **Live WebSocket Telemetry**: Dedicated foreground bridge service (`wss://.../ws/phone`) syncing battery levels, network status, active app, and lock states in real time.
* **Zero-Touch Automation**: Android `AccessibilityService` dispatches touch gestures, executes remote typing, handles app switching, and sets alarms.
* **Notification Bridge**: Listens for and relays WhatsApp, Telegram, and SMS notifications directly to the desktop HUD.

### 🧠 5. Deep Cognitive Memory & Knowledge Graph
* **Hybrid Memory Architecture**:
  * **Episodic Memory**: SQLite database capturing cross-turn dialogue contexts and past user interactions.
  * **Semantic Vector RAG**: ChromaDB memory engine retrieving relevant knowledge snippets.
  * **Knowledge Graph**: Entity-relationship extraction linking personal preferences, people, projects, and habits.
  * **Encrypted Long-Term Vault**: Fernet-encrypted store for sensitive user credentials and private state.

### 🌐 6. Military-Grade Geospatial 3D Intelligence (`frontend/`)
* **CesiumJS 3D Globe**: Real-time tracking layers for commercial flights (OpenSky), orbital satellites (N2YO), marine AIS traffic, and geopolitical hotspots.
* **Dynamic Island HUD**: Floating pill displaying audio waveforms, active emotion states, and live system resource utilization.

---

## 🏗️ Repository Architecture

```
aura-assistant/
├── backend/                        # FastAPI High-Performance Asynchronous Server
│   ├── agents/                     # Specialized agent personas (Girlfriend, Companion, Jarvis)
│   ├── core/                       # Language routing, audio pipelines, turn controllers
│   ├── engines/                    # Autonomous executors (ScreenAgent, Phone, KnowledgeGraph, RAG)
│   ├── memory/                     # ChromaDB RAG, Episodic SQLite, and Ephemeral stores
│   ├── routers/                    # Modular REST endpoints (System, Payment, Voice, Screen, Phone)
│   ├── threads/                    # Automation modules (Apps, Filesystem, Media, Communications)
│   ├── tests/                      # Full test suite (131+ passing unit/integration tests)
│   ├── tts_dispatch.py             # Chatterbox Turbo sole synthesis dispatcher
│   └── main.py                     # ASGI root and real-time WebSocket orchestration
├── frontend/                       # Primary React 18 + Vite Glassmorphic Dashboard (Port 5173)
│   ├── src/components/canvas/      # 60 FPS HTML5 canvas particle fields and visualizers
│   ├── src/components/dashboard/   # Telemetry HUDs, Central Crystal Orb, Phone companion cards
│   ├── src/components/geo/         # CesiumJS 3D geospatial intelligence globe
│   ├── src/components/ui/          # Dynamic Island, Floating Dock, Cinematic Subtitles
│   └── src/hooks/                  # Cognitive orchestrator, AudioStreamPlayer, contextual awareness
├── frontend-avatar/                # 3D Living Human Avatar Frontend (Port 5174)
│   ├── src/components/avatar/      # Three.js R3F humanoid GLB mesh, viseme morph targets
│   ├── src/components/hud/         # Glassmorphic status overlays, VU meters, subtitles
│   └── src/services/               # Binary audio streaming & WebSocket listeners
├── android_companion/              # Native Android Kotlin Companion App
│   ├── app/src/main/java/.../      # PhoneBridgeService, AccessibilityService, NotificationListener
│   └── app/src/main/res/           # Material layouts, accessibility configurations
├── scripts/                        # Management, Automation & Verification Utilities
│   ├── start_servers.ps1           # Master stack orchestrator (Backend, Frontends, Tunnel, Ollama)
│   ├── reverify_all.py             # 81-check naming, registry & routing verification test suite
│   ├── open_frontend.ps1           # Standalone window launcher (Edge/Chrome app mode)
│   └── create_desktop_shortcuts.ps1# Windows desktop shortcut generator
├── tts_benchmark/                  # Benchmark suite & evaluation tools
│   ├── chatterbox/                 # Chatterbox latency and RTF evaluation
│   └── router/                     # Chatterbox Turbo dialect classification & router unit tests
├── docker-compose.yml              # Local container orchestrator with GPU pass-through
└── Start-Alita-Servers.bat         # One-click launcher controller
```

---

## ⚡ Quick Start & Deployment

### 📋 Prerequisites

| Component | Minimum Version | Verified |
| :--- | :--- | :--- |
| **OS** | Windows 10/11 or Ubuntu 22.04 | Windows 11 64-bit |
| **Python** | 3.11.x | 3.11.9 |
| **Node.js** | 20.x | v20.18.0 |
| **GPU Acceleration** | CUDA 12.1+ compatible NVIDIA GPU | RTX 4GB+ VRAM |
| **LLM Host** | Ollama local daemon | `qwen3:4b` |

---

### 💻 1. Automated One-Click Launch (Windows)

To start the entire server stack silently in the background:
```bat
Start-Alita-Servers.bat
```
*Press `1` or wait 5 seconds. It will automatically initialize Ollama, start FastAPI on port 8000, launch the web dashboard on port 5173, and mount the 3D avatar on port 5174.*

---

### 🛠️ 2. Manual Native Setup

#### Step A: Configure Backend
```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate
# Linux
source venv/bin/activate

# Install PyTorch with CUDA 12.1
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121

# Install requirements
pip install -r requirements.txt
```

#### Step B: Launch Primary LLM (Ollama)
```bash
ollama serve
# In another terminal:
ollama pull qwen3:4b
```

#### Step C: Run Backend Server
```bash
python main.py
```
*API will be live at `http://localhost:8000` (Swagger docs at `/docs`).*

#### Step D: Run Web Frontends
```bash
# Terminal 1 — Main Assistant Dashboard
cd frontend
npm install
npm run dev

# Terminal 2 — 3D Living Human Avatar
cd frontend-avatar
npm install
npm run dev
```

---

## 📊 Hardware & VRAM Benchmark

Tested on an **NVIDIA RTX Mobile (4 GB VRAM)** running CUDA 12.1:

| Component | Allocation | Role |
| :--- | :---: | :--- |
| **Qwen3:4B (Ollama)** | ~2,100 MB | Fast-inference reasoning & multi-turn dialogue |
| **Chatterbox-Turbo (350M)** | ~800 MB | Unified expressive neural speech synthesis |
| **Faster-Whisper (Streaming)** | ~180 MB | Real-time speech-to-text |
| **CUDA Runtime / PyTorch Allocator** | ~350 MB | System buffer |
| **Total Peak VRAM** | **~3,430 MB** | **Fits safely inside 4,096 MB budget** |

---

## 🧪 Comprehensive Verification & Test Suite

The repository maintains strict verification standards with an automated end-to-end testing pipeline:

```bash
# Windows (using project virtual environment)
backend\venv\Scripts\python.exe -m pytest backend/tests/ -v
backend\venv\Scripts\python.exe scripts/reverify_all.py
backend\venv\Scripts\python.exe tts_benchmark/router/test_language_router.py

# Or with activated venv (Windows / Linux / macOS)
pytest backend/tests/ -v
python scripts/reverify_all.py
python tts_benchmark/router/test_language_router.py

# Verify production frontend builds
cd frontend && npm run build
cd ../frontend-avatar && npm run build
```

**Results:**
* ✅ **Pytest**: 131/131 tests passing (100% green).
* ✅ **Integrity Checks**: 81/81 checks passing.
* ✅ **Router Tests**: 45/45 tests passing.
* ✅ **Vite Production Bundlers**: 0 build errors across both web interfaces.

---

## 🔒 Security & Privacy

* **Local-First Processing**: Voice recognition, LLM inference, vision analysis, and memory queries execute 100% locally on your machine.
* **Encrypted Secrets**: Long-term state and private tokens are secured with Fernet symmetric encryption.
* **Deterministic Sandboxing**: Shell commands and automation scripts validate paths, enforce argument vectorization, and reject unsanitized shell inputs.

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.
