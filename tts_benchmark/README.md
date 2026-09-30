# MJ AI Assistant — TTS Benchmark Suite

This benchmark suite evaluates and tunes the dual-engine TTS architecture:
1. **ChatTTS** (`chattts/`): English-only speech synthesis, natural human prosody, emotional effects.
2. **F5-TTS** (`f5tts/`): Multilingual synthesis for Hindi, Hinglish, and mixed Hindi-English sentences.
3. **TTS Language Router** (`router/`): Deterministic routing engine.
4. **Results** (`results/`): Quantitative metrics (latency, parameters) and qualitative audio observations.
5. **Speakers** (`speakers/`): Persisted deterministic speaker representations.
