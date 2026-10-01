# MJ/ALITA — ENGINEERING RULES

You are working on an existing, complex Android voice assistant called MJ/ALITA.

Treat the existing repository as a real production-style codebase that has accumulated technical debt through many previous iterations.

## CURRENT INTENDED ARCHITECTURE

The target architecture is currently:

1. Local LLM: Qwen3 4B through Ollama.
2. Android automation: the existing custom Android automation application.
3. TTS: Chatterbox Turbo only.
4. Existing voice input / speech recognition pipeline should be preserved unless a concrete problem requires modification.
5. Existing memory, tools, UI, communication layers and other working components should be preserved unless evidence shows they are defective.

## HARD CONSTRAINTS

Do NOT introduce another:

* LLM
* TTS engine
* model router
* AI verification model
* fallback model
* orchestration framework
* agent framework
* dependency
* database
* messaging system
* abstraction layer

unless there is a specific demonstrated requirement that cannot be satisfied by the existing architecture.

Before introducing anything new, explain:

1. The exact problem.
2. Why the current architecture cannot solve it.
3. The proposed component.
4. Why a simpler solution is insufficient.
5. The maintenance cost.
6. How it can be removed later.

No technology should be added merely because it is technically interesting.

## CHANGE CONTROL

For non-trivial work:

1. Inspect before modifying.
2. Identify the root cause before implementing a solution.
3. State assumptions explicitly.
4. Separate confirmed evidence from hypotheses.
5. Prefer the smallest change that solves the demonstrated problem.
6. Do not modify unrelated subsystems.
7. Do not combine multiple unrelated refactors into one change.
8. Preserve existing working behavior.
9. Maintain a rollback path.
10. Test after every meaningful change.

## NO ARCHITECTURAL DRIFT

Do not redesign MJ/ALITA merely because another architecture may look cleaner.

The question is:

"Does the existing architecture demonstrably fail to satisfy a requirement?"

not:

"Can we design something more sophisticated?"

Prefer:

* deterministic logic over unnecessary AI decisions
* existing components over new components
* explicit state over hidden state
* simple tool calls over multi-stage agent loops
* measurable performance over subjective optimization

## AI-GENERATED CODE DISCIPLINE

Never trust a hypothesis merely because it sounds technically plausible.

For every important diagnosis use:

HYPOTHESIS
→ EVIDENCE
→ EXPERIMENT
→ RESULT
→ CONCLUSION

Do not label something "confirmed" without evidence.

## PERFORMANCE DISCIPLINE

Every performance optimization must define:

* baseline
* bottleneck
* change
* post-change measurement

Never optimize based solely on intuition.

## SAFETY DURING REPOSITORY MODIFICATION

Before deleting or replacing code:

* identify all references
* identify runtime usage
* identify configuration usage
* identify dependency usage
* confirm it is obsolete

Do not silently delete experimental or legacy code.

Mark obsolete components explicitly before removal.

## MODEL RULES

Qwen3 4B is the current LLM.

Chatterbox Turbo is the current TTS engine.

Do not change these merely because another model might be faster or more powerful.

Only recommend a model change when there is measured evidence that the current model cannot satisfy a required performance or quality target.

## AGENT BEHAVIOR

When asked to investigate:
DO NOT MODIFY CODE unless explicitly instructed.

When asked to implement:
modify only what is required by the approved plan.

When uncertain:
inspect more evidence rather than inventing assumptions.

When a task unexpectedly expands:
stop and report the scope expansion rather than silently redesigning the system.

## DEFINITION OF DONE

A change is complete only when:

* implementation is complete
* existing behavior is preserved
* relevant tests pass
* new behavior is tested
* errors and failure modes are considered
* performance impact is measured when relevant
* the final diff is reviewed
* unnecessary changes are removed
* documentation/configuration is updated when required

Your objective is to make MJ/ALITA simpler, more reliable, faster and easier to maintain — not more complex.
