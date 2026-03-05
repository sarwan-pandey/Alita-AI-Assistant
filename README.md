# Aura Assistant

An emotionally intelligent AI assistant. Real-time 3D particle figure that
mirrors your movements. Understands what you say and how you feel when you say it.
```
Webcam → MediaPipe (browser) → Three.js figure @ 60 FPS
Microphone → WebSocket → Whisper STT + Wav2Vec2 SER → Phi-3 Mini → Piper TTS
```

> **Phase 1 MVP.** Monolithic backend. Single-machine local deployment.
> Tested on RTX mobile 4 GB VRAM, CUDA 12.1, Node 20, Python 3.11.

---

## Prerequisites

Install these before anything else.

| Requirement | Version | Check |
|---|---|---|
| Python | 3.11.x | `python --version` |
| Node | 20.x | `node --version` |
| npm | 10.x | `npm --version` |
| CUDA Toolkit | 12.1 | `nvcc --version` |
| NVIDIA Driver | ≥ 530 | `nvidia-smi` |
| Git | any | `git --version` |

---

## Project Structure (Phase 1 — Monolithic)
```
aura-assistant/
├── frontend/          # Vite + React 18 + Three.js + MediaPipe
│   ├── .env.local     # Supabase keys + WS URL  ← you create this
│   └── src/
├── backend/           # FastAPI — single main.py
│   ├── .env           # JWT secret + Stripe secret  ← you create this
│   ├── main.py        # ALL backend logic lives here in Phase 1
│   └── models/        # Drop your .gguf file here  ← gitignored
├── piper/
│   └── voices/        # Piper voice .onnx files  ← gitignored
├── docker-compose.yml
└── README.md
```

---

## Quick Start — Native (Recommended for GPU)

Running natively is strongly preferred over Docker for Phase 1 because GPU
pass-through in containers adds complexity and overhead on Windows/WSL2.
Follow these steps exactly and in order.

---

### Step 1 — Clone and enter the repo
```bash
https://github.com/sarwan-pandey/Alita-AI-Assistant.git
cd Alita-AI-Assistant
```

---

### Step 2 — Download the Phi-3 Mini GGUF model
```bash
# Create the models directory
mkdir -p backend/models

# Option A: use huggingface-cli (pip install huggingface_hub first)
huggingface-cli download \
  microsoft/Phi-3-mini-4k-instruct-gguf \
  Phi-3-mini-4k-instruct-q4.gguf \
  --local-dir backend/models \
  --local-dir-use-symlinks False

# Option B: manual download
# Visit: https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf
# Download: Phi-3-mini-4k-instruct-q4.gguf  (~2.2 GB)
# Place at: backend/models/phi-3-mini-4k.gguf
```

> **Rename the file** to match `MODEL_PATH` in your `.env`: `phi-3-mini-4k.gguf`

---

### Step 3 — Download Piper TTS binary + voice
```bash
mkdir -p piper/voices

# Download Piper binary for your OS from:
# https://github.com/rhasspy/piper/releases/latest

# Linux (x86_64):
wget https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz
tar -xzf piper_linux_x86_64.tar.gz -C piper/
# Binary will be at: piper/piper

# Windows: download piper_windows_amd64.zip, extract into piper/

# Download a voice (en-US lessac medium — good quality, fast):
wget -P piper/voices \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx

wget -P piper/voices \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

---

### Step 4 — Configure backend environment
```bash
# Create the backend .env file:
cat > backend/.env << 'EOF'
# Supabase — get these from your Supabase project dashboard → Settings → API
SUPABASE_JWT_SECRET=your-supabase-jwt-secret-here

# Stripe — get from Stripe Dashboard → Developers → Webhooks → signing secret
STRIPE_WEBHOOK_SECRET=whsec_your_stripe_webhook_secret_here

# LLM — path relative to where you run uvicorn (i.e. from backend/)
MODEL_PATH=./models/phi-3-mini-4k.gguf

# Optional overrides (defaults shown):
# LLM_N_GPU_LAYERS=28
# LLM_N_CTX=4096
# AUDIO_SAMPLE_RATE=16000
EOF
```

> **Supabase JWT secret:** Dashboard → Settings → API → JWT Settings → `JWT Secret`

---

### Step 5 — Configure frontend environment
```bash
cat > frontend/.env.local << 'EOF'
# Supabase — same project as above
VITE_SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
VITE_SUPABASE_ANON_KEY=your-supabase-anon-key-here

# Backend WebSocket URL — do not change for local dev
VITE_WS_BACKEND_URL=ws://localhost:8000/ws
EOF
```

> **Supabase values:** Dashboard → Settings → API → `URL` and `anon public` key

---

### Step 6 — Install backend dependencies
```bash
cd backend

# Create isolated virtual environment
python -m venv venv

# Activate it:
# Linux / macOS:
source venv/bin/activate
# Windows PowerShell:
# .\venv\Scripts\Activate.ps1
# Windows CMD:
# venv\Scripts\activate.bat

# Upgrade pip first — old pip can mishandle CUDA wheel selection
pip install --upgrade pip

# Install PyTorch with CUDA 12.1 support FIRST (order matters)
pip install torch==2.3.0+cu121 torchaudio==2.3.0+cu121 torchvision==0.18.0+cu121 \
  --extra-index-url https://download.pytorch.org/whl/cu121

# Install llama-cpp-python with CUDA/cuBLAS support
# CMAKE_ARGS tells the C++ build system to enable GPU offloading
CMAKE_ARGS="-DLLAMA_CUBLAS=on" \
FORCE_CMAKE=1 \
pip install llama-cpp-python==0.2.77 --no-cache-dir

# Install remaining dependencies
pip install -r requirements.txt

cd ..
```

> **Windows note:** Replace `CMAKE_ARGS="-DLLAMA_CUBLAS=on"` with
> `set CMAKE_ARGS=-DLLAMA_CUBLAS=on` in CMD, or
> `$env:CMAKE_ARGS="-DLLAMA_CUBLAS=on"` in PowerShell,
> then run `pip install llama-cpp-python==0.2.77 --no-cache-dir` on the next line.

---

### Step 7 — Install frontend dependencies
```bash
cd frontend
npm install
cd ..
```

---

### Step 8 — Start the backend

Open **Terminal 1** and run:
```bash
cd backend
source venv/bin/activate   # or .\venv\Scripts\Activate.ps1 on Windows

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Expected startup output (in order):**
```
INFO  | Device: cuda | Model: ./models/phi-3-mini-4k.gguf
INFO  | Loading Phi-3 Mini GGUF — offloading 28 layers to GPU…
INFO  | ✓ Phi-3 Mini loaded.
INFO  | Loading Whisper tiny.en…
INFO  | ✓ Whisper tiny.en loaded on cuda.
INFO  | Loading Wav2Vec2-tiny SER…
INFO  | ✓ Wav2Vec2 SER loaded. Labels: [...]
INFO  | All engines initialised.
INFO  | === Ready to accept connections. ===
INFO  | Uvicorn running on http://0.0.0.0:8000
```

**Verify VRAM is within budget:**
```bash
# In a separate terminal while the backend is running:
nvidia-smi

# You should see roughly:
#   2100 MiB  ← Phi-3 Mini (28 layers)
#    150 MiB  ← Whisper tiny
#     90 MiB  ← Wav2Vec2
#    350 MiB  ← CUDA runtime + PyTorch
# ─────────────────────────────────────
#  ~2690 MiB  total  (well under 4096 MiB)
```

**Or hit the health endpoint:**
```bash
curl http://localhost:8000/health
# Expected:
# {
#   "status": "ok",
#   "engines": { "llm": true, "whisper": true, "wav2vec2": true },
#   "vram": { "allocated_gb": 2.69, "device_name": "NVIDIA GeForce RTX ..." }
# }
```

---

### Step 9 — Start the frontend

Open **Terminal 2** and run:
```bash
cd frontend
npm run dev
```

**Expected output:**
```
  VITE v5.x.x  ready in 312 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: http://YOUR_IP:5173/
```

Open `http://localhost:5173` in **Chrome** or **Edge** (Chromium required for
AudioWorklet + WebAssembly SIMD used by MediaPipe).

---

### Step 10 — First run checklist

Work through these in order. Each validates one layer of the stack.
```
[ ] Browser opens without console errors on http://localhost:5173
[ ] Auth screen appears with "AURA" branding and ambient particles
[ ] Sign in with Google completes and redirects back to the app
[ ] HUD shows "connected" green dot (WebSocket authenticated successfully)
[ ] Browser prompts for camera permission → grant it
[ ] 3D wireframe figure appears and tracks your face/pose in real time
[ ] Browser prompts for microphone permission → grant it
[ ] Speak a sentence → HUD ring animates while listening
[ ] After ~600ms silence: emotion label updates in HUD
[ ] LLM response tokens stream into the chat log
[ ] TTS audio plays back through speakers
[ ] nvidia-smi shows < 3.8 GB VRAM consumed
```

If any step fails, see the **Troubleshooting** section below.

---

## Supabase Setup (Google OAuth)

The backend JWT validation requires a Supabase project with Google OAuth enabled.

1. Create a free project at [supabase.com](https://supabase.com)
2. Go to **Authentication → Providers → Google** and enable it
3. Follow the [Supabase Google OAuth guide](https://supabase.com/docs/guides/auth/social-login/auth-google) to create OAuth credentials in Google Cloud Console
4. Add `http://localhost:5173` to **Authentication → URL Configuration → Redirect URLs**
5. Copy your **JWT Secret**, **URL**, and **anon key** into the `.env` files as shown in Steps 4–5

---

## Troubleshooting

**`llama-cpp-python` builds but uses CPU (0 GPU layers offloaded)**
```bash
# Verify cuBLAS was linked during build:
python -c "from llama_cpp import llama_cpp; print(llama_cpp.__file__)"
# Then check:
python -c "from llama_cpp import Llama; m = Llama('./backend/models/phi-3-mini-4k.gguf', n_gpu_layers=1, verbose=True)"
# Look for: "ggml_cuda_init: found X CUDA devices" in output
# If missing, rebuild: CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
```

**WebSocket connects then immediately drops with code 4003**
```bash
# JWT secret mismatch. Verify:
# 1. backend/.env SUPABASE_JWT_SECRET matches Supabase Dashboard → Settings → API → JWT Secret
# 2. The token is being sent as a query param: ws://localhost:8000/ws?token=<JWT>
# 3. Check backend logs for "JWT validation failed" with the specific JWTError message
```

**MediaPipe WASM fails to load / "SharedArrayBuffer is not defined"**
```
# The Vite dev server must set COOP/COEP headers. Verify vite.config.js contains:
#   "Cross-Origin-Opener-Policy": "same-origin"
#   "Cross-Origin-Embedder-Policy": "require-corp"
# These are already set in the provided vite.config.js.
# If using a custom proxy, add these headers there too.
```

**MediaPipe loads but landmarks are wrong / mirrored**
```
# This is expected on first run — the SCALE_X = -3.0 flip in AuraCanvas.jsx
# mirrors the coordinate system. If your figure moves opposite to you,
# change SCALE_X from -3.0 to 3.0 in both WireframeHuman and DenseParticleField.
```

**Whisper returns empty transcripts**
```bash
# Minimum audio required: 1 second (MIN_SPEECH_SAMPLES in main.py §10c)
# If you're speaking shorter phrases, lower it:
#   MIN_SPEECH_SAMPLES = settings.audio_sample_rate * 0.5  # 500ms minimum
# Also verify microphone sample rate is 16 kHz:
python -c "import sounddevice as sd; print(sd.query_devices())"
```

**VRAM exceeds 4 GB**
```bash
# Reduce GPU layers for Phi-3 to push more computation to CPU:
# In backend/.env, add:
#   LLM_N_GPU_LAYERS=20    # was 28 — saves ~400 MB VRAM, modest speed cost

# Or switch Whisper/Wav2Vec2 to CPU entirely by changing in main.py:
#   .to(settings.device)  →  .to("cpu")
# VRAM impact: saves ~240 MB, transcription ~2x slower
```

**Piper TTS produces no audio / "Piper binary not found"**
```bash
# Verify piper binary is executable:
chmod +x ./piper/piper
./piper/piper --version

# Test TTS directly:
echo "Hello from Aura" | ./piper/piper \
  --model ./piper/voices/en_US-lessac-medium.onnx \
  --output_file /tmp/test.wav
aplay /tmp/test.wav   # Linux
# or open /tmp/test.wav in any audio player
```

**`torch` installs CPU version instead of CUDA**
```bash
# Verify CUDA build:
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
# Expected: True 12.1
# If False: reinstall torch with the --extra-index-url flag shown in Step 6
```

---

## Environment Variable Reference

### `backend/.env`

| Variable | Required | Description |
|---|---|---|
| `SUPABASE_JWT_SECRET` | ✅ | From Supabase Dashboard → Settings → API → JWT Secret |
| `STRIPE_WEBHOOK_SECRET` | ✅ | From Stripe Dashboard → Webhooks → Signing secret |
| `MODEL_PATH` | ✅ | Path to `.gguf` file, relative to `backend/` |
| `LLM_N_GPU_LAYERS` | optional | Default `28`. Reduce to save VRAM |
| `LLM_N_CTX` | optional | Default `4096`. Context window size |
| `LLM_MAX_TOKENS` | optional | Default `512`. Max response length |
| `LLM_TEMPERATURE` | optional | Default `0.7`. Response creativity |

### `frontend/.env.local`

| Variable | Required | Description |
|---|---|---|
| `VITE_SUPABASE_URL` | ✅ | `https://YOUR_ID.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | ✅ | Supabase anon/public key |
| `VITE_WS_BACKEND_URL` | ✅ | Default `ws://localhost:8000/ws` |

---

## VRAM Budget (RTX 4 GB Mobile)

| Component | VRAM |
|---|---|
| Phi-3 Mini 4-bit GGUF (28 GPU layers) | ~2100 MB |
| Whisper tiny.en FP16 | ~150 MB |
| Wav2Vec2-base SER FP16 | ~90 MB |
| CUDA runtime + PyTorch allocator | ~350 MB |
| **Total** | **~2690 MB** |
| **Headroom** | **~1306 MB** |

---

## What's Coming in Phase 2

- Refactor `main.py` into `core/`, `engines/`, `routers/`, `schemas/` modules
- `memory/chroma_rag.py` — ChromaDB persistent RAG for Premium tier
- Domain LoRA support (Medical, Fitness)
- Zero-shot voice cloning
- Bluetooth HRV biometric sync
- React Native port

---

## License

MIT
