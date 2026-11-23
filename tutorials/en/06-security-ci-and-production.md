# Chapter 06: Going Public on GitHub — Security Sweep & Auto-Checks

> 🌐 **Language Switcher**: **[简体中文](../zh/06-security-ci-and-production.md)** | **English**
> 🧭 **Navigation**: **[← Prev: 05 · Automated Grading & `#eval` UI](./05-eval-driven-flywheel-and-dashboard.md)** | **[Back to Tutorial Hub](../README.md)**

---

## 1. What We're Doing Before Clicking "Make Public"
Your app works and your 5-stage scoreboard is green! Before flipping your GitHub repo from Private to **Public**, let's spend 10 minutes on four essential checks:
1. **Check old Git commits, not just today's files**: Why deleting an API key in a new commit still leaves it wide open in Git history;
2. **Keep local tools local (`127.0.0.1`)**: Why you shouldn't expose an unauthenticated local agent to the open internet;
3. **Add standard open-source files**: `LICENSE`, `.env.example`, `SECURITY.md`, and a clear legal disclaimer;
4. **Set up an automatic bouncer (GitHub Actions CI)**: Run offline unit tests, spec checks, and secret scans automatically on every push.

---

## 2. Four Classic Mistakes People Make When Publishing Vibe-Coded Repos

1. **"I deleted `.env` yesterday, so I'm safe!" (Nope!)**:
   If Commit #1 accidentally included an API key or your real personal resume and Commit #2 deleted it, **anyone running `git log -p` on your public repo can still read Commit #1 in two seconds**.
2. **Binding to `0.0.0.0` on a public server without login**:
   Local dev tools skip user login for convenience. If you deploy `app.py` to a cloud VM on `0.0.0.0:8000`, strangers can burn through your Gemini quota or control your browser session. Keep the default `127.0.0.1:8000` (localhost only).
3. **Unchecked filenames on download routes**:
   Routes like `GET /api/download/{filename}` must strip directory paths and verify prefixes so nobody can pass `../../` to read private files outside `output/`.
4. **Forgetting a `LICENSE` and Disclaimer**:
   No `LICENSE` file legally means *"nobody else is allowed to use or modify this code."* And for any project involving browser automation, put an unmistakable **Educational & Research Use Only** disclaimer right at the top of `README.md`.

---

## 3. From Scratch: Ask AI to Run a Pre-Release Security Sweep

Paste this into Antigravity or Codex right before making a repo public:

```text
I want to make this repository Public on GitHub. Run a pre-release security and open-source sweep first:
1. Check every commit in Git history (`git rev-list --all`) to verify we never committed API keys (`AIzaSy`, `sk-`, `PRIVATE KEY`), real personal resumes, or internal company project IDs;
2. Verify `.gitignore` blocks `.env`, `.gemini_runtime.json`, `chrome-profile/`, `output/`, and `*.xlsx`;
3. Put a clear bilingual Disclaimer & Security Notice at the very top of `README.md` (personal learning/research only, follow site ToS, keep `127.0.0.1:8000` local unless auth is added);
4. Add `LICENSE` (MIT), `.env.example`, `SECURITY.md`, and `.github/workflows/ci.yml` to automatically run offline unit tests, check our 5 OpenSpec docs, and scan for leaked secrets on every push.
```

---

## 4. Try These Safety Checks Right Now

### Check 1: Scan Every Commit in Git History for Leaked Keys
Run this one-liner in your terminal—seeing `0` hits means your history is clean:
```bash
python3 -c '
import subprocess
commits = subprocess.check_output(["git", "rev-list", "--all"]).decode().splitlines()
pat = r"(AIzaSy[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{20,}|ya29\.[0-9A-Za-z_-]{20,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY)"
hits = [c for c in commits if subprocess.run(["git", "grep", "-n", "-E", pat, c], capture_output=True).returncode == 0]
print(f"Checked {len(commits)} commits — leaked secret hits: {len(hits)}")
'
```
*(If a key ever shows up: **revoke and replace the key in your cloud console first**, then clean Git history before publishing!)*

### Check 2: See What GitHub Actions Runs on Every Push ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml))
Without needing any paid cloud secrets, `.github/workflows/ci.yml` runs three fast checks in seconds whenever code is pushed:
1. Stage 3, 4, and 5 offline unit tests (city priority, alternating-weekend traps, daily pay math, bottom demotion, junk-free stats);
2. Format checks across all 5 `openspec/specs/` files;
3. A repo-wide secret scan that fails the build if a key ever slips in.

### Check 3: Flip Two Free Switches on GitHub (Takes 1 Minute)
1. In your repo, go to **Settings → Code security** and turn on **Secret scanning** and **Push protection** (GitHub will block accidental key pushes before they even land!);
2. In your personal GitHub **Emails** settings, turn on **Keep my email addresses private** if you'd rather not expose your personal email in commits.

---

## 5. You Made It! Plus a Fun Mini-Challenge 🎉

You've just walked through the complete playbook for turning Vibe Coding into reliable Agent Engineering. Here are the 5 plain-English rules to carry into every future AI project:

1. **Write a short plan before letting AI touch code** (`Explore → Propose → Apply → Archive`);
2. **One stage, one job** (low temperature `0.1` for reading facts, higher `0.4` for brainstorming);
3. **Keep scoring math separate from browser scraping** (so you can test in milliseconds offline);
4. **Let Python do arithmetic, let LLMs write explanations** (zero made-up averages);
5. **Review AI-drafted answer keys once, then auto-grade forever**.

### 🎯 Try One Full Cycle Yourself!
Test out your new workflow with a quick 10-minute improvement on this repo:
> **Mini-Challenge**: Right now in Stage 4 (`core/boss_crawler.py`), `BOSS在线` (*recruiter online*) adds `+2.0` points. What if Phase 2's `HR活跃度` (*recruiter activity*) says `"刚刚活跃"` (*just active*) or `"今日活跃"` (*active today*)? Try giving active recruiters a small bonus so responsive hiring managers rank higher!
> 1. Ask AI: `OpenSpec explore: check how recruiter activity is currently scored in Stage 4`;
> 2. Ask for an `OpenSpec propose` → skim the short plan;
> 3. Say `Start apply` → run `.venv/bin/python eval/stage4_eval/evaluate_stage4_ranking.py` and check `/#eval`;
> 4. Say `Run archive` to save your updated spec!

Have fun building reliable AI Agents—and if this guide helped you out, give the repo a ⭐ Star on GitHub!
