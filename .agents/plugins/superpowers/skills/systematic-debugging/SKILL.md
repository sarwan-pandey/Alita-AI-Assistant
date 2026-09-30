---
name: systematic-debugging
description: Structured root-cause analysis workflow. Prevents premature guessing, enforces evidence-based debugging, traces data flow end-to-end, and verifies fixes with live tests.
---

# Systematic Debugging Workflow

This skill equips both Gemini and Claude with deep root-cause analysis procedures.

## When to Activate
- When tests fail unexpectedly.
- When facing complex cross-module errors (concurrency, race conditions, async deadlocks, circular imports).
- When intermittent or environmental issues occur.

## Methodology

1. **Information Gathering & Symptom Analysis**
   - Read the exact traceback, error code, and error message.
   - Do NOT guess what went wrong—check the exact line numbers and inspected variable states.

2. **Hypothesis Formation & Testing**
   - Formulate a falsifiable hypothesis for the failure.
   - Test the hypothesis by inspecting runtime values, AST structure, or execution logs.

3. **Root Cause Isolation**
   - Distinguish between the *immediate symptom* (e.g., `AttributeError`) and the *underlying cause* (e.g., incorrect method name, uninitialized singleton, or stale schema).

4. **Surgical Resolution**
   - Implement the fix directly at the root.
   - Avoid adding defensive try/except blocks that swallow underlying failures silently.
