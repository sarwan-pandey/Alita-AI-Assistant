# Superpowers Core Engineering Rules

These rules apply universally to any model running within Antigravity IDE (including Google Gemini and Anthropic Claude):

1. **Strict Verification Over Assumption**:
   - Never declare a bug fixed or a feature complete without executing a test or verification command that demonstrates concrete success.
   - When fixing a defect, first isolate and observe the failing condition, then verify the green result.

2. **Non-Destructive Modifications**:
   - Preserve all existing interfaces, endpoints, data contracts, and docstrings unless explicitly instructed to deprecate them.
   - When updating models, speech engines, or WebSocket handlers, ensure defensive fallbacks and backward compatibility are maintained.

3. **Root Cause Resolution (No Shallow Patches)**:
   - Always trace to the foundational error (e.g., circular imports, lock deadlocks, schema mismatches, route collisions) rather than suppressing errors with catch-all exceptions or monkey-patching.

4. **Multi-Model Parity**:
   - Code written and workflows used must remain strictly portable between Gemini 2.0, Claude 3.5/3.7, and local Ollama models.
