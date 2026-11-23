# Chapter 06: From Local Prototype to Public Release — Security Audit, CI Gates & OSS Checklist

> 🌐 **Language Switcher**: **[简体中文](../zh/06-security-ci-and-production.md)** | **English**
> 🧭 **Navigation**: **[← Prev: 05 · Eval-Driven Flywheel & Dashboard](./05-eval-driven-flywheel-and-dashboard.md)** | **[Back to Tutorial Hub](../README.md)**

---

## 1. What You Will Learn
1. **The #1 Pre-Open-Source Blind Spot**: Why deleting a leaked key in your latest commit doesn't hide it—and how to scan your **entire Git commit history**;
2. **Local Agent Security Boundaries**: `127.0.0.1` loopback binding, `0o600` runtime config permissions, path-traversal guards, and legal disclaimers;
3. **Standard Open-Source Governance Files**: `LICENSE`, `.env.example`, `SECURITY.md`, and bilingual `README.md`;
4. **Automated GitHub Actions CI ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml))**: Guarding offline unit tests, OpenSpec AST validity, and secret hygiene on every push and PR.

---

## 2. Mental Model: 4 Security Traps Before Clicking "Make Public"

1. **Git History Exposure**: If Commit #1 accidentally included an API key, `.env`, real personal resume, or internal cloud project ID and Commit #2 deleted it, **anyone running `git log -p` on your public repo can still extract it in seconds**.
2. **Unauthenticated Public Binding (`0.0.0.0` vs. `127.0.0.1`)**: Local developer agents typically omit multi-user login. Binding Uvicorn to `0.0.0.0` on a public server exposes your LLM quota and local browser controls to the entire internet.
3. **Path Traversal on File Endpoints**: Endpoints like `GET /api/download/{filename}` or `GET /api/eval/runs/{run_id}` must validate regex allowlists and `.resolve()` directory prefixes to block `../../etc/passwd` reads.
4. **Missing License & Legal Disclaimer**: Without a `LICENSE` file, a public GitHub repo defaults to "All Rights Reserved." Any project involving browser automation must also state clear educational/research-only terms.

---

## 3. Vibe Coding From Scratch: Pre-Release Security Audit Prompt

Before making your repository public, run this prompt with Antigravity or Codex:

```text
I am preparing to make this repository public on GitHub. Run a full security and open-source readiness audit:
1. Scan the entire Git commit history (`git rev-list --all`) for leaked API keys (`AIzaSy`, `sk-`, `PRIVATE KEY`), real personal resumes, internal project IDs, or internal environment comments;
2. Verify `.gitignore` excludes `.env`, `.gemini_runtime.json`, `chrome-profile/`, `output/`, and `*.xlsx`;
3. Add a prominent bilingual Disclaimer & Security Notice at the top of `README.md` (educational/research use only, respect platform ToS, never expose `127.0.0.1:8000` publicly without auth);
4. Add `LICENSE` (MIT), `.env.example`, `SECURITY.md`, and a GitHub Actions workflow `.github/workflows/ci.yml` that runs Stage 3/4/5 offline unit checks, validates all 5 OpenSpec AST specs, and scans for leaked credentials on every push/PR.
```

---

## 4. Verify Right Now on This Repo: The 4 Defense Layers

### Layer 1: Full Git Commit History Secret Audit
Run this one-liner anytime before pushing or publishing:
```bash
python3 -c '
import subprocess
commits = subprocess.check_output(["git", "rev-list", "--all"]).decode().splitlines()
pat = r"(AIzaSy[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{20,}|ya29\.[0-9A-Za-z_-]{20,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY)"
hits = [c for c in commits if subprocess.run(["git", "grep", "-n", "-E", pat, c], capture_output=True).returncode == 0]
print(f"Scanned {len(commits)} commits — secret hits: {len(hits)}")
'
```
*(If a secret ever hits, immediately **revoke/rotate** the credential first, then rewrite history with `git filter-repo`.)*

### Layer 2: Server-Side Hardening ([`app.py`](../../app.py) & [`core/boss_crawler.py`](../../core/boss_crawler.py))
- Loopback-only binding (`127.0.0.1:8000`);
- `os.chmod(RUNTIME_CFG_FILE, 0o600)` on local runtime config, with `GET /api/status` returning only boolean `ai_ready` (never plaintext keys);
- Strict `SAFE_ID_PATTERN` + `.resolve()` prefix checks on every file download and eval report lookup.

### Layer 3: Zero-Secret GitHub Actions CI ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml))
On every `push` and `pull_request` to `main`, CI verifies in seconds (requiring zero cloud API keys):
1. Offline unit tests across Stage 3, Stage 4, and Stage 5;
2. 100% OpenSpec AST compliance across all 5 master specs in `openspec/specs/`;
3. Repository-wide regex secret scanning.

### Layer 4: GitHub Repository Settings (Final 1-Minute Step)
1. Enable **Settings → Code security → Secret scanning & Push protection**;
2. Enable **Keep my email addresses private** under your personal GitHub email settings if desired.

---

## 5. Graduation Summary & Hands-On Challenge 🚀

Congratulations! You have walked through the entire lifecycle of building a **Spec-Driven, Eval-Driven Multi-Stage AI Agent**:
1. **OpenSpec Guardrails**: `Explore → Propose → Apply → Archive` + AST-verified living specs;
2. **Stage Decoupling & Temperature Stratification**: `temp=0.1` factual extraction vs. `temp=0.4` creative strategy generation;
3. **Pure Logic vs. Brittle I/O Separation**: Sub-millisecond offline job ranking (`rank_and_filter_jobs`) decoupled from Playwright CDP;
4. **Python Math + Grounded LLM Reasoning**: Compliant-pool 6D statistics paired with domain-neutral, anti-hallucination Gemini insights;
5. **Human-in-the-Loop Eval Flywheel**: `gemini-4-argon` Ground Truth drafting → human Manual Review → automated `NDCG@8` & 4D judge regression on `/#eval`.

### 🎯 Your Hands-On Capstone Exercise
Practice a complete OpenSpec cycle yourself on this repository:
> **Challenge**: Add a configurable bonus in Stage 4 (`core/boss_crawler.py`) for jobs where `HR活跃度` indicates active/online recruiters, and verify via `evaluate_stage4_ranking.py` that `NDCG@8` stays `>= 0.975`!
> 1. Prompt: `OpenSpec explore: audit how HR activity is currently scored in Stage 4`;
> 2. Run `Propose` → review the 4 files under `openspec/changes/`;
> 3. Run `Apply` → execute `.venv/bin/python eval/stage4_eval/evaluate_stage4_ranking.py` and inspect `/#eval`;
> 4. Run `Archive` → merge the delta spec and verify the OpenSpec AST validator passes!

Happy Agent Engineering! If this tutorial and repository helped you, feel free to ⭐ Star or Fork the project and build your own Spec-Driven Agents!
