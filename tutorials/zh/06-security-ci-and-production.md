# 第 06 章：从本地原型到开源/上线——安全审计、CI 门禁与发布 Checklist

> 🌐 **语言切换**: **简体中文** | **[English](../en/06-security-ci-and-production.md)**
> 🧭 **章节导航**: **[← 上一章：05 · Eval 评测飞轮与看板](./05-eval-driven-flywheel-and-dashboard.md)** | **[返回教程总目录](../README.md)**

---

## 1. 本章你将学会
1. **Make Public 前的致命盲区**：为什么只删最新代码的密钥没用？如何用一条脚本扫描**全量 Git Commit 历史**；
2. **本地 Agent 服务的部署安全边界**：`127.0.0.1` 绑定、运行时配置文件权限 `0o600`、防路径遍历与爬虫法律免责声明；
3. **开源项目标配四件套**：`LICENSE`、`.env.example`、`SECURITY.md` 与双语 `README.md`；
4. **GitHub Actions CI 自动化守护（[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)）**：让每次提交自动核验离线单测、OpenSpec AST 与密钥防泄露。

---

## 2. 思维框架：Vibe Coding 原型公开前最容易忽略的 4 大安全风险

用 AI 快速写完项目准备点 GitHub `Make public` 时，90% 的个人开发者会踩以下四个雷区：

1. **Git 历史残留（Git History Exposure）**：第 1 次 commit 不小心把 `.env`、API Key、真实个人简历或公司内部项目 ID 提交了进去，第 2 次 commit 把它删了。**一旦仓库公开，任何人执行 `git log -p` 都能在 3 秒内把第 1 次 commit 里的密钥扒出来！**
2. **公网裸奔风险（`0.0.0.0` vs `127.0.0.1`）**：本地工具型 Agent 通常没有做多租户登录鉴权，如果把 Uvicorn 启动地址写成 `0.0.0.0:8000` 部署到云服务器，全网任何人都能调你的接口消耗你的 Gemini 配额甚至操控调试浏览器；
3. **文件读写路径遍历（Path Traversal）**：下载 Excel（`GET /api/download/{filename}`）或加载评测报告（`GET /api/eval/runs/{run_id}`）如果不校验文件名与父目录边界，攻击者传入 `../../etc/passwd` 就会造成任意文件读取；
4. **缺少开源协议与免责声明**：没有 `LICENSE` 的 GitHub 仓库在法律上默认“保留所有权利”，别人无法合法参考；涉及网页采集的项目没有显著免责声明会带来不必要的合规风险。

---

## 3. 从 0 到 1 实战：上线前让 Antigravity / Codex 做一次全仓安全审计

在公开仓库前，直接把下面这条审计 Prompt 发给你的 Vibe Coding 工具：

### 💬 上线前安全审计与加固 Prompt 模板
```text
我准备将这个仓库在 GitHub 上设为 Public，请先帮我做一次完整的开源前安全与工程合规检查：
1. 扫描全量 Git commit 历史（`git rev-list --all`），检查是否曾经提交过任何 API Key（`AIzaSy` / `sk-` / `PRIVATE KEY`）、真实个人简历、内部项目 ID 或公司域环境注释；
2. 检查 `.gitignore` 是否已严格排除 `.env`、`.gemini_runtime.json`、`chrome-profile/`、`output/` 和 `*.xlsx`；
3. 在 `README.md` 顶部添加醒目的中英双语免责声明（仅供个人学习与架构研究，严禁商业化高频抓取；提醒 `app.py` 默认仅绑定 `127.0.0.1:8000`，严禁无鉴权暴露公网）；
4. 补齐开源标配文件：`LICENSE`（MIT）、`.env.example`、`SECURITY.md`，并编写 `.github/workflows/ci.yml` 在每次 Push/PR 时自动跑离线单元测试、OpenSpec AST 规范校验与密钥防泄露扫描。
```

---

## 4. 对照本仓库落地实现：四大安全防线逐一拆解

### 防线 1：全量 Git Commit 历史密钥扫描命令（随时可自查）
把下面这段命令跑一遍，确认输出全部为 `0 hits` 再公开仓库：
```bash
python3 -c '
import subprocess
commits = subprocess.check_output(["git", "rev-list", "--all"]).decode().splitlines()
pat = r"(AIzaSy[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{20,}|ya29\.[0-9A-Za-z_-]{20,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY)"
hits = [c for c in commits if subprocess.run(["git", "grep", "-n", "-E", pat, c], capture_output=True).returncode == 0]
print(f"已扫描 {len(commits)} 个历史 Commit，密钥泄露命中数: {len(hits)}")
'
```
> ⚠️ **万一命中了怎么办？** 第一时间去云控制台**作废并轮换（Rotate）该密钥**，然后用 `git filter-repo` 或新建干净孤立分支重写历史后再推送。

### 防线 2：服务端代码级安全加固（见 [`app.py`](../../app.py) 与 [`core/boss_crawler.py`](../../core/boss_crawler.py)）
- **本地回环绑定**：`uvicorn.run("app:app", host="127.0.0.1", port=8000)`；
- **运行时凭证最小权限**：本地 `.gemini_runtime.json` 写入后立即执行 `os.chmod(RUNTIME_CFG_FILE, 0o600)`（仅当前系统用户可读），且 `GET /api/status` 只返回布尔值 `ai_ready: true/false`，**绝不向前端回传明文 Key**；
- **路径穿越拦截**：所有文件名先过正则白名单 `SAFE_ID_PATTERN` 或 `os.path.basename()`，再用 `.resolve()` 校验必须位于目标目录内部。

### 防线 3：GitHub Actions 持续集成门禁（见 [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)）
不需要配置任何云端密钥，CI 在每次 Push / PR 时自动在几秒内完成三件事：
1. **Stage 3 / 4 / 5 纯离线核心逻辑回归测试**（城市优先级、薪资/作息边界、异地低薪垫底降权、合规池统计隔离、零领域污染）；
2. **OpenSpec 主规范 AST 100% 合规校验**（确保文档与规范永不腐烂）；
3. **代码库密钥正则扫描**（一旦有人误提交 Key 直接标红阻断合并）。

### 防线 4：开启 GitHub 平台级安全开关（最后 1 分钟操作）
在把仓库设为 Public 前后，进入 GitHub 仓库页面：
1. **Settings → Code security** → 开启 **Secret scanning** 与 **Push protection**（GitHub 会在你 `git push` 含密钥的 commit 时直接在服务端拦截拒绝）；
2. **Settings → Emails**（个人账号设置）→ 若不想暴露个人邮箱，开启 **Keep my email addresses private**。

---

## 5. 全教程毕业总结与进阶练习 🚀

恭喜你完整走完了从 **0 到生产级 Spec-Driven & Eval-Driven Agent 系统** 的全部 7 个章节！回顾一下你掌握的核心工程武器库：

1. **用 OpenSpec 管住 Vibe Coding**：`Explore → Propose → Apply → Archive` 四步法 + AST 语法树硬校验；
2. **物理拆分与温度分层**：把复杂任务拆成职责单一的 Stage，收敛提取用 `temp=0.1`、策略发散用 `temp=0.4`；
3. **纯逻辑与脆弱 I/O 分离**：把过滤粗排从浏览器爬虫中剥离，让核心智能毫秒级可测；
4. **算术归 Python，推理归 LLM**：杜绝统计幻觉与模板领域污染；
5. **Human-in-the-Loop 评测飞轮**：强模型起草真值 → 人类审核锁死 → 确定性门禁 + `NDCG@8` + LLM-as-a-Judge 持续回归。

### 🎯 留给你的毕业实战挑战（动手练一遍完整流程！）
试着在本仓库上亲自走一轮完整的 **OpenSpec 四步循环**，给系统增加一个小而实用的新特性：
> **挑战题目**：在 Stage 4 初筛打分（`core/boss_crawler.py`）中，为 **`HR活跃度 == "在线"` 或 `"刚刚活跃"`** 的岗位增加可配置的活跃度权重，并在 Stage 4 离线评测中验证 `NDCG@8` 不退化！
> 1. 对 Antigravity / Codex 说：`OpenSpec explore：盘点目前 HR 活跃度在 Stage 4 打分中的权重设计`；
> 2. 发起 `Propose` → 审阅 `openspec/changes/` 下的 4 份文档；
> 3. 回复 `开始 apply` → 运行 `.venv/bin/python eval/stage4_eval/evaluate_stage4_ranking.py` 对比 `#eval` 看板分值；
> 4. 回复 `执行 archive` → 合并规范并通过 CI 校验！

祝你在构建下一代可靠 AI Agent 系统的道路上玩得开心！如果这套教程和仓库对你有帮助，欢迎给仓库点一颗 ⭐ Star 或 Fork 开启你的二次创作！
