---
name: test-driven-development
description: Strict Test-Driven Development (TDD) workflow. Enforces writing reproducing tests first, proving failure, making minimal code changes to pass, and confirming regression safety.
---

# Test-Driven Development (TDD) Workflow

This skill equips both Gemini and Claude with the rigorous TDD loop from the superpowers toolkit.

## When to Activate
- When fixing any bug, crash, or unexpected behavior.
- When implementing a new feature, endpoint, or engine integration.
- When refactoring existing code to prevent regressions.

## The 4-Step Cycle

1. **Step 1: Write Reproducing Test (RED)**
   - Before editing any production code, write a targeted test that asserts the desired behavior.
   - Run the test and observe that it fails for the expected reason (not due to syntax or environmental errors).

2. **Step 2: Implement Minimal Code Fix (GREEN)**
   - Make the smallest, most precise edit to production code necessary to satisfy the test.
   - Do not refactor other parts of the system during this step.

3. **Step 3: Verify the Fix**
   - Run the targeted test to confirm it now passes (turns green).
   - If it still fails, diagnose the delta without making arbitrary guesses.

4. **Step 4: Regression Check & Clean Up**
   - Run the wider test suite to ensure no collateral damage or broken pipelines.
   - Clean up any scratch files or test artifacts.
