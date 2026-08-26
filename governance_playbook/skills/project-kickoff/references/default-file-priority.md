# Default File Priority

Use this priority when rebuilding project context at conversation start.

## Primary (highest signal)
- `docs/project/REQUIREMENTS.md`
- `docs/需求差异分析报告.md`
- `docs/详细任务清单.md`

## Secondary (project structure and release state)
- `README.md`
- `PROJECT_STRUCTURE.md`
- `docs/project/WBS.md`
- `docs/project/version_history.md`
- `docs/project/version_management.md`

## Optional (role-specific)
- `docs/project/frontend_requirements_gap_analysis.md`
- `docs/*周报*.md`
- `docs/*handoff*.md`

## Fallback Search Patterns
Use these patterns when exact files are missing:
- `*requirement*`
- `*需求*`
- `*task*` or `*任务*`
- `*gap*` or `*差异*`
- `*milestone*` or `*里程碑*`
- `*risk*` or `*风险*`

## Conflict Rule
If files disagree, prefer the newest file by modification time and mention the conflict in one sentence.

