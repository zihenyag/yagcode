# Architecture

YagCode is a local Coding Agent Harness. The model produces one structured action at a time; repository code owns execution, feedback, memory, policy, and stop conditions.

## Components

- `src/yagcode/core/`: loop, budgets, feedback, compaction, stop and steer behavior.
- `src/yagcode/domain/`: action/result schemas and parsing.
- `src/yagcode/tools/`: bounded file, search, patch, and command adapters.
- `src/yagcode/policy/`: approval tokens, path policy, capability binding, privacy grants, and credential boundaries.
- `src/yagcode/memory/`: scoped project/profile memory and promotion rules.
- `src/yagcode/api/`: loopback HTTP/SSE API consumed by the desktop renderer.
- `apps/desktop/`: Electron main/preload plus React renderer.
- `src/yagcode/cli.py` and `src/yagcode/tui.py`: standalone CLI/TUI product entry.

## Runtime Flow

1. User opens a project and creates or selects a thread.
2. Harness builds the active context from the task, repository facts, policy state, memory, and previous objective feedback.
3. Provider abstraction performs one model call.
4. Action parser accepts only strict structured actions.
5. Policy and capability code decide whether the action is allowed, blocked, or needs human approval.
6. Tool dispatcher executes the action in the declared boundary.
7. Test/lint/typecheck or tool result becomes objective feedback for the next step.
8. Stop conditions pause or finish the run; user reviews diff and evidence before accepting.

The GitHub Pages site is outside the runtime path. It is a static product page.
