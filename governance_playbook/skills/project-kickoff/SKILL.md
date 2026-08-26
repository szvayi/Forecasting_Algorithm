---
name: project-kickoff
description: Build project context at the start of a new conversation by reading requirement, task, progress, and risk files in the current workspace, then output a concise alignment brief and next actions. Use when starting work on an unfamiliar project, resuming a long-running project, or recovering context after long chats.
---

# Project Kickoff

## Overview
Run a standard kickoff scan for the current workspace before execution. Reconstruct project state from files, then present one concise alignment brief.

## Workflow

### 0. Apply First-Principles Mode
Before reading files or proposing plans, apply these constraints:
- Start from original user intent and root problem, not default templates.
- If goal or motivation is unclear, ask for confirmation before execution.
- If a better path exists, explicitly recommend it with tradeoffs.
- Prefer root-cause fixes over patch stacking.
- Keep outputs decision-focused and explain key "why" behind decisions.
### 1. Discover Candidate Files
List candidate files with `rg --files` and prefer these paths when present:
- `docs/project/REQUIREMENTS.md`
- `docs/需求差异分析报告.md`
- `docs/详细任务清单.md`
- `docs/project/frontend_requirements_gap_analysis.md`
- `docs/project/MVP_MILESTONE_GOVERNANCE_STANDARD.md`
- `README.md`
- `PROJECT_STRUCTURE.md`
- `docs/project/WBS.md`
- `docs/project/version_history.md` or `docs/project/version_management.md`
- Project-specific dashboard docs in `docs/`.

If a preferred path is missing, continue with the closest equivalent file.

### 2. Read Minimal, High-Signal Context
Read only the files needed to answer:
- What is the current goal?
- What is in scope now?
- What is done, doing, blocked, and risky?
- What is the next highest-priority action?
- What is the current MVP milestone gate status?

Avoid loading unrelated long references.

### 3. Produce a Standard Kickoff Brief
Output in Chinese using this exact section order:
1. `目标状态` (current target and scope boundary)
2. `当前进度` (done + in progress)
3. `主要风险` (top 1-3 risks)
4. `阻塞项` (explicit blockers)
5. `下一步` (up to 3 concrete actions)

Keep the brief compact and decision-oriented.

If goal motivation is missing, append one short line:
- 待确认动机 (why this milestone matters now).`r`n`r`nIf goal motivation is missing, append one short line:`r`n- `待确认动机` (why this milestone matters now).

### 4. Enforce MVP Milestone Governance
Apply these rules by default:
- Complex projects must be advanced by deliverable MVP milestones.
- Milestone completion requires explicit gates (function, data, quality, stability, observability).
- Keep scope discipline: close the current milestone before expansion.

### 5. Agent Assignment and Capability Loop
When task distribution is requested, output:
- `任务 -> 子代理` mapping (PM/Architecture/UI/Frontend/Backend/QA etc.).
- Matching rationale by domain fit, tool fit (skill/MCP), and risk fit.
- Capability updates after milestone closure (promote, keep, or retrain).

### 6. Start Execution
After the brief, immediately continue with the user request. Do not stop at analysis unless the user explicitly asks to pause.

## Output Rules
- Prefer facts from files over assumptions.
- If files conflict, state conflict and pick the most recent file by timestamp.
- If critical files are missing, state what was missing and proceed with best available context.
- Keep the kickoff brief short enough to read in under one minute.

## References
For reusable file-priority and fallback patterns, see [default-file-priority.md](references/default-file-priority.md).


