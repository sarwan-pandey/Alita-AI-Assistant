# MJ AI Assistant — TTS Benchmark Suite

This benchmark suite evaluates and tunes the dual-engine TTS architecture:
1. **ChatTTS** (`chattts/`): English-only speech synthesis, natural human prosody, emotional effects.
2. **Chatterbox** (`chatterbox/`): Primary cloud Chatterbox Multilingual NIM and local Chatterbox Turbo engine.
3. **TTS Language Router** (`router/`): Deterministic routing engine.
4. **Results** (`results/`): Quantitative metrics (latency, parameters) and qualitative audio observations.
5. **Speakers** (`speakers/`): Persisted deterministic speaker representations.
