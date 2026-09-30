---
name: architectural-refactor
description: Safe, multi-file architectural refactoring workflow. Preserves API contracts, eliminates dead code, manages circular dependency resolution, and validates system integrity.
---

# Architectural Refactoring Workflow

This skill guides large-scale refactoring operations across backend engines, routers, and frontend React components.

## When to Activate
- When reorganizing code across multiple files or directories.
- When resolving duplicate code paths or redundant route registrations.
- When breaking circular dependencies between core modules.

## Protocol

1. **Pre-Refactor Audit**
   - Check all incoming and outgoing dependencies (using `code-review-graph` MCP or grep).
   - Document all callers, routes, and consumers of the components being modified.

2. **Incremental Extraction**
   - Perform extractions one module at a time.
   - Run unit tests after each extracted module before moving to the next.

3. **Contract Preservation**
   - Maintain backwards-compatible aliases or redirects where external clients depend on legacy paths.
   - Use dynamic imports (`__getattr__` or `get_settings()`) when resolving circular import hazards.

4. **Dead Code Elimination**
   - Verify that unreferenced files or unreachable code blocks are verified as unused before removal.
