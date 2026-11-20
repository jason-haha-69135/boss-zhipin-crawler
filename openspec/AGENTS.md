# OpenSpec Instructions for AI Coding Agents (`AGENTS.md`)

This project uses **OpenSpec** for Spec-Driven Development (SDD). Specifications in `openspec/specs/` are the single source of truth for what is currently built and verified, while `openspec/changes/` contains active delta proposals.

---

## 1. Directory Structure

```text
openspec/
├── project.md                                  # Global project context, models, security & architecture conventions
├── AGENTS.md                                   # This instruction file
├── specs/                                      # Living specifications (Source of Truth)
│   ├── stage1-resume-parser/
│   │   └── spec.md
│   └── stage2-query-generator/
│       └── spec.md
└── changes/                                    # Active change proposals (Delta Specs)
    └── archive/                                # Completed & merged change proposals
```

---

## 2. Three-Stage Workflow

### Stage A: Creating Change Proposals (`propose`)
Before implementing a new stage or modifying an existing stage's behavior, create a directory `openspec/changes/<change-id>/` containing:
1. `proposal.md` — `# Change: <Title>`, `## Why`, `## What Changes`, `## Impact`.
2. `design.md` — Technical design decisions, module interfaces, and `eval/stage<N>_eval/` benchmark design.
3. `tasks.md` — Numbered implementation and evaluation checklist (`- [ ] 1.1 ...`).
4. `specs/<capability>/spec.md` — Delta specification using `## ADDED Requirements`, `## MODIFIED Requirements`, or `## REMOVED Requirements`.

### Stage B: Implementing & Evaluating Changes (`apply`)
1. Read `proposal.md`, `design.md`, and `tasks.md`.
2. Implement each item in code and `eval/stage<N>_eval/`.
3. Run the stage evaluation benchmark (using `gemini-4-argon` as default LLM-as-a-Judge) and verify all scenarios pass.
4. Mark all tasks in `tasks.md` as completed (`- [x]`).

### Stage C: Archiving Changes (`archive`)
Once evaluation gates pass and the user approves:
1. Merge delta requirements (`ADDED` / `MODIFIED` / `REMOVED`) into `openspec/specs/<capability>/spec.md`.
2. Move `openspec/changes/<change-id>/` to `openspec/changes/archive/YYYY-MM-DD-<change-id>/`.
3. Synchronize high-level architecture notes in `system_design.md`.

---

## 3. Strict OpenSpec Parser & Validator Rules (`markdown-parser.ts` & `validator.ts`)

Every `openspec/specs/<capability>/spec.md` file MUST strictly obey the following AST rules enforced by the OpenSpec parser:

1. **Required Top-Level Sections**:
   - `# <Capability> Specification`
   - `## Purpose` (MUST be at least 50 characters and MUST NOT contain `TBD`)
   - `## Requirements`
2. **Requirement Block Format**:
   - Header MUST match `^### Requirement: (.+)$`
   - The requirement body text immediately following the header MUST contain uppercase normative keywords **`SHALL`** or **`MUST`**.
   - Every `### Requirement:` block MUST contain **at least one** `#### Scenario:` block.
3. **Scenario Block Format**:
   - Header MUST match `^#### Scenario: (.+)$` (strictly 4 hashes `####`).
   - Scenario body MUST use structured bullet points:
     - `- **WHEN** <trigger or input condition>`
     - `- **THEN** <expected deterministic outcome>`
     - `- **AND** <additional outcome or assertion>`
4. **Delta Spec Format (Inside `openspec/changes/<change-id>/specs/<capability>/spec.md`)**:
   - Top-level delta headers MUST be one or more of:
     - `## ADDED Requirements`
     - `## MODIFIED Requirements`
     - `## REMOVED Requirements`
     - `## RENAMED Requirements`
   - Each requirement inside `ADDED` or `MODIFIED` MUST include the complete `### Requirement: <Name>` text (`SHALL`/`MUST`) and at least one `#### Scenario: <Name>` (`WHEN`/`THEN`).
