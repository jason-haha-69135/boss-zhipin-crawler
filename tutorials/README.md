<div align="center">

# 手把手教你用 Vibe Coding 做出靠谱的 AI Agent
### Hands-On Guide: Building a Reliable Multi-Stage AI Agent with Spec & Eval

🌐 **[简体中文目录 (Chinese)](#简体中文教程目录)** &nbsp;|&nbsp; **[English Track](#english-tutorial-track)** &nbsp;|&nbsp; **[返回项目主页 / Back to Repo](../README.md)**

</div>

---

<a id="简体中文教程目录"></a>

## 🇨🇳 简体中文版：从空白文件夹到能上线的求职分析 Agent

### 为什么要写这套教程？
很多刚用上 **Antigravity、Codex、Claude Code、Cursor** 这类 Vibe Coding 工具的朋友，都会经历过山车一样的心态：
- **第 1 天**：“太爽了！我说了两句话，AI 就帮我把页面和后端全写出来了！”
- **第 3 天**：“坏了……让它改个小功能，结果把前面写好的逻辑全改崩了；大模型还老瞎编数据，根本不敢拿出去用。”

其实问题不在工具，在于**我们缺了一套“管住 AI”的简单办法**。

这套教程就拿本仓库这个真实的 **BOSS直聘智能求职助手** 当例子，像老朋友带路一样，带你模拟**从一个空文件夹开始**，怎么一步步跟 AI 聊天：怎么挖需求、怎么定规矩、怎么写代码、怎么测效果，最后怎么安全地发到 GitHub 上。**全程说人话、不堆造词，所有命令复制就能跑！**

### 推荐你这样学（两条腿走路最稳）
1. **先把现成项目跑起来（看结果）**：跟着第 00 章花 10 分钟把本仓库跑通，点点界面、跑跑命令，心里先有个直观印象；
2. **开个空文件夹自己试一遍（练手感）**：每章都给你准备好了可以直接复制给 Antigravity / Codex 的**大白话 Prompt 模板**，你可以跟着亲手搭一遍。

```mermaid
flowchart LR
    C0["00 · 先跑起来\n不装爬虫也能玩转全流程"]
    C1["01 · 给 AI 立规矩\n先写方案再改代码"]
    C2["02 · 读简历与想搜词\nStage 1 & Stage 2"]
    C3["03 · 拼链接与排岗位\nStage 3 & Stage 4"]
    C4["04 · 算数据与写点评\nStage 5 不瞎编数字"]
    C5["05 · 给 AI 打分考试\n人工把关 + 评测看板"]
    C6["06 · 安全检查与开源\n查黑历史 + 自动测试"]

    C0 --> C1 --> C2 --> C3 --> C4 --> C5 --> C6
```

### 📑 中文分章目录

| 章节 | 标题 | 这一章主要讲什么大白话道理？ | 对应仓库里的代码 |
| :---: | :--- | :--- | :--- |
| **00** | **[10 分钟跑通项目（不用配爬虫也能玩）](./zh/00-quickstart-and-sandbox.md)** | 配好 API Key，直接打开网页看 5 个阶段的打分看板，用几条命令单独试玩每个模块 | `app.py`, `.env.example`, `start_chrome.sh` |
| **01** | **[别让 AI 乱改代码：用 OpenSpec 给它立规矩](./zh/01-openspec-foundation.md)** | 为什么不能上来就让 AI 写代码？教你“先盘点 → 写方案 → 再动手 → 最后存档”四步法 | `openspec/project.md`, `openspec/AGENTS.md`, `openspec/specs/` |
| **02** | **[从简历到搜索词：为什么要拆成两步走？（Stage 1 & 2）](./zh/02-stage1-stage2-resume-to-queries.md)** | 读简历要老实（温度调低不瞎编），想搜索词要灵活（温度调高多给路子）；顺手把姓名电话打码抹掉 | `core/resume_parser.py`, `core/query_generator.py` |
| **03** | **[拼搜索链接与挑好岗位：把打分和爬虫拆开（Stage 3 & 4）](./zh/03-stage3-stage4-intent-and-ranking.md)** | 怎么搜才能不漏掉大厂好岗位？怎么防止把“单双休”错当成“双休”？把异地、低薪岗排到最后但别删掉 | `core/intent_parser.py`, `core/boss_crawler.py` |
| **04** | **[算术归 Python，分析归大模型：写出不瞎编的报告（Stage 5）](./zh/04-stage5-grounded-6d-analysis.md)** | 千万别让大模型自己数数算平均工资！先用 Python 剔除干扰项算准数字，再让大模型结合简历写点评 | `core/gemini_analyzer.py`, `static/app.js` |
| **05** | **[怎么知道改得好不好？搭一套自动打分与可视化看板](./zh/05-eval-driven-flywheel-and-dashboard.md)** | 先让强模型帮拟一份参考答案，咱们人工看一眼确认没问题，以后每次改代码都自动跑分对比 | `eval/eval_store.py`, `eval/stage1_eval/` ~ `eval/stage5_eval/` |
| **06** | **[准备发到 GitHub 公开：安全大扫除与自动检查](./zh/06-security-ci-and-production.md)** | 检查历史提交里有没有漏掉密钥和真简历，加上免责声明、开源协议和每次提交自动跑的测试 | `.github/workflows/ci.yml`, `SECURITY.md`, `LICENSE` |

---
---

<a id="english-tutorial-track"></a>

## 🌐 English Track: Build a Reliable AI Agent Step-by-Step (Plain-English Edition)

### Why This Guide?
When you start building with **Vibe Coding tools** (Antigravity, Codex, Claude Code, Cursor), single-file demos feel like magic—until day three, when fixing one bug breaks two existing features and the LLM starts making up numbers.

Using this repository (**BOSS Zhipin Job Intelligence Agent**) as a working example, this 7-part guide walks you **from an empty folder to a public-ready 5-stage AI Agent** in plain, practical developer English—no buzzword soup, just clear mental models and copy-pasteable prompts and commands.

### 📑 English Chapter Index

| Chapter | Title | Plain-English Takeaway | Key Files in Repo |
| :---: | :--- | :--- | :--- |
| **00** | **[Get It Running in 10 Minutes (No Scraper Needed)](./en/00-quickstart-and-sandbox.md)** | Plug in your Gemini key, explore the 5-stage `/#eval` dashboard, and test individual endpoints with `curl` | `app.py`, `.env.example`, `start_chrome.sh` |
| **01** | **[Stop AI From Breaking Your Code: Rules with OpenSpec](./en/01-openspec-foundation.md)** | Why "plan before code" saves hours: `Explore → Propose → Apply → Archive` + simple script checks for docs | `openspec/project.md`, `openspec/AGENTS.md`, `openspec/specs/` |
| **02** | **[From Resume to Search Queries: Why Split Into Two Steps? (Stages 1 & 2)](./en/02-stage1-stage2-resume-to-queries.md)** | Be strict when reading facts (`temp=0.1`), creative when brainstorming searches (`temp=0.4`), and scrub personal info in code | `core/resume_parser.py`, `core/query_generator.py` |
| **03** | **[Search Links & Job Ranking: Separate Scoring From Scraping (Stages 3 & 4)](./en/03-stage3-stage4-intent-and-ranking.md)** | Avoid killing search results with extra words, catch tricky "every-other-weekend" wording, and push bad-fit jobs to the bottom without deleting them | `core/intent_parser.py`, `core/boss_crawler.py` |
| **04** | **[Let Python Do the Math, Let LLMs Write the Advice (Stage 5)](./en/04-stage5-grounded-6d-analysis.md)** | Never ask an LLM to average 150 salaries—filter out junk jobs in Python first, then feed clean numbers to Gemini | `core/gemini_analyzer.py`, `static/app.js` |
| **05** | **[How Do You Know It Got Better? Automated Grading & `#eval` UI](./en/05-eval-driven-flywheel-and-dashboard.md)** | Have a stronger model draft answer keys, review them yourself once, then grade every future change automatically | `eval/eval_store.py`, `eval/stage1_eval/` ~ `eval/stage5_eval/` |
| **06** | **[Going Public on GitHub: Security Sweep & Auto-Checks](./en/06-security-ci-and-production.md)** | Scan old Git commits for leaked keys, keep local servers off the public internet, and add GitHub Actions tests | `.github/workflows/ci.yml`, `SECURITY.md`, `LICENSE` |
