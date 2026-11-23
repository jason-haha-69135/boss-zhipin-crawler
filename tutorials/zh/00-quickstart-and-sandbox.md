# 第 00 章：10 分钟先把项目跑起来（不用配爬虫也能玩转全流程）

> 🌐 **语言切换**: **简体中文** | **[English](../en/00-quickstart-and-sandbox.md)**
> 🧭 **章节导航**: **[返回教程总目录](../README.md)** | **[下一章：01 · 给 AI 立规矩（OpenSpec） →](./01-openspec-foundation.md)**

---

## 1. 这一章咱们干什么？
在从零开始动手写代码之前，咱们先花 **10 分钟** 把现成的项目跑起来看看长啥样。你会发现：
1. 只要配好 Python 环境和一个 Gemini 密钥（用免费的 AI Studio API Key 或者 Google Cloud 账号都行，代码会自动识别）；
2. **根本不用开 Chrome 浏览器去爬网站**，直接打开网页就能看完整的 **5 阶段打分看板 (`/#eval`)**；
3. 用几条简单的 `curl` 命令，就能单独试玩“拼搜索链接”、“给岗位打分排序”、“生成分析报告”这几个核心功能。

---

## 2. 先看一眼全局：这项目到底是怎么干活的？

很多刚学做 Agent 的朋友，上来就想把“读简历 + 搜岗位 + 挑岗位 + 写总结”全塞进一段长长的 Prompt 里。结果一跑起来，要么慢得要死，要么中间哪一步错了根本没法查。

所以在这个项目里，我们就像工厂流水线一样，把它切成了 **5 个清清楚楚的小步骤（Stage 1 ~ Stage 5）**：

```mermaid
flowchart LR
    S1["📄 Stage 1\n读简历提重点\n(顺手抹掉姓名电话)"]
    S2["🎯 Stage 2\n结合意向城市\n想出10条搜岗词"]
    S3["🧭 Stage 3\n把话翻译成\nBOSS直聘搜索链接"]
    S4["📐 Stage 4\n抓岗位并打分\n把异地/低薪排最后"]
    S5["📊 Stage 5\nPython算准工资分布\n大模型结合简历点评"]

    S1 --> S2 --> S3 --> S4 --> S5
```

> [!TIP]
> **对新手最友好的一点**：除了“真去网页上拉数据”那一下需要浏览器，**其他所有动脑子的环节（读简历、生搜词、拼链接、给岗位打分排序、写六维报告）全都有独立的本地接口**！就算你完全不想折腾浏览器爬虫，也能把整套 Agent 学透、跑通。

---

## 3. 第一步：下载代码、装好环境（3 分钟）

打开终端，一行行复制运行就行：

```bash
# 1. 下载代码并进入文件夹
git clone git@github.com:jason-haha-69135/boss-zhipin-crawler.git
cd boss-zhipin-crawler

# 2. 建一个独立的 Python 虚拟环境（免得把你电脑里别的项目包搞乱）
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖包
pip install -r requirements.txt

# 4. 复制一份环境变量配置文件
cp .env.example .env
```

接着配一下 **Gemini 的访问凭证**（下面两种方式**任选一个**就行，[`core/gemini_client.py`](../../core/gemini_client.py) 会自动看你配了哪个就用哪个）：

### 方式 A：用 Google AI Studio 的 API Key（最省事，个人首选）
```bash
export GEMINI_API_KEY="填你自己的_GEMINI_API_KEY"
```

### 方式 B：用 Google Cloud 登录（适合已经在用 GCP 的同学）
```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="填你的_GCP项目ID"
```

---

## 4. 第二步：启动网页，先逛一圈评测看板（2 分钟）

在终端运行：

```bash
python app.py
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就说明跑起来了！打开浏览器看两个页面：

1. **先看 5 阶段打分看板（不用做任何操作就能看）**：打开 `http://127.0.0.1:8000/#eval`
   - 点点最上面一排 **STAGE 1 → STAGE 2 → STAGE 3 → STAGE 4 → STAGE 5** 五张卡片；
   - 仓库里已经自带了跑好的测试报告，你能直接看到每一关是怎么打分的（比如简历信息提准了没、搜索链接拼对了没、排序有没有把高薪好岗排前面）。
2. **再看主页面（传份假简历试试）**：打开 `http://127.0.0.1:8000/`
   - 先在上传框上面选一个 **意向城市**（比如 `上海`），然后把仓库自带的测试假简历 `eval/dataset/stage1/qualified/QUAL-01.pdf` 拖进去；
   - 等几秒钟，你就能看到提炼出来的简历标签（姓名电话已经被自动打码抹掉了）和 10 条推荐搜索词；你还可以试着把城市切成 `杭州`，看看搜索词是不是秒级自动更新！

---

## 5. 第三步：不开浏览器，用命令单独试玩 Stage 3 和 Stage 4

保持刚才的 `python app.py` 别关，新开一个终端窗口，复制下面两条命令跑跑看：

### 小实验 1：看看 Stage 3 怎么把一句话变成 BOSS直聘链接 (`POST /api/intent/parse`)
```bash
curl -s -X POST http://127.0.0.1:8000/api/intent/parse \
  -H "Content-Type: application/json" \
  -d '{
    "query": "互联网软件行业的Java开发工程师岗位，月薪至少1.2w",
    "target_city": "杭州"
  }' | python3 -m json.tool
```
**你可以留意这三点**：
- 搜索词 `query` 变成了干干净净的 `"Java开发工程师"`（把前面“互联网软件行业的”去掉了，为什么这么干咱们第 03 章细聊）；
- 杭州自动换成了官方城市编号 `"101210100"`，`1.2w` 换成了 `10-20K` 档位码 `"405"`；
- 最下面的 `boss_url` 是一条直接点开就能在 BOSS直聘搜出结果的真实网址！

### 小实验 2：看看 Stage 4 怎么给岗位打分、把不合适的排到最后 (`POST /api/jobs/rank`)
```bash
curl -s -X POST http://127.0.0.1:8000/api/jobs/rank \
  -H "Content-Type: application/json" \
  -d '{
    "top_k": 2,
    "intent": {
      "raw_query": "广州Java开发工程师，月薪至少10K，周末双休",
      "query": "Java开发工程师",
      "city_name": "广州",
      "city_code": "101280100",
      "salary_code": "405",
      "min_salary_k": 10,
      "industry_keywords": ["互联网", "软件"],
      "require_double_weekend": true
    },
    "resume_profile": {"core_skills": ["Java", "MySQL", "SpringBoot"]},
    "jobs": [
      {"岗位名称": "Java开发工程师", "薪资范围": "18-25K", "工作地点": "深圳·南山", "所属行业": "互联网", "福利待遇": "周末双休", "技能标签": "Java"},
      {"岗位名称": "Java开发工程师", "薪资范围": "6-8K", "工作地点": "广州·天河", "所属行业": "互联网", "福利待遇": "周末双休", "技能标签": "Java"},
      {"岗位名称": "高级Java后端开发", "薪资范围": "12-18K", "工作地点": "广州·海珠", "所属行业": "软件", "福利待遇": "周末双休", "技能标签": "Java, MySQL"}
    ]
  }' | python3 -m json.tool
```
**你可以留意这两点**：
- 虽然第 3 个岗位叫 `"高级Java后端开发"`（跟 `"Java开发工程师"` 字面不完全一样），但它靠关键词重合和技能匹配拿到了最高分排第 1；
- 第 1 个岗位虽然钱多但远在**深圳**（异地），第 2 个岗位只有 **6-8K**（不够 10K 底薪），它俩都被贴上了 `is_demoted: true` 标签排到了最后面，但并没有被偷偷删掉（总条数还是 3 条）。

### 小实验 3：（可选）想试真爬虫的话
运行 `./start_chrome.sh`，在弹出来的 Chrome 窗口里扫码登录一次 BOSS直聘，之后回主网页点任意一条推荐词就能看实时抓取了。

---

## 6. 本章打卡清单
- [x] `python app.py` 成功跑起来了；
- [x] 打开 `/#eval` 看过了 5 个阶段的打分看板；
- [x] 在主页传了一次 `QUAL-01.pdf` 测试简历；
- [x] 用 `curl` 试玩了拼链接和岗位排序接口。

热身结束！下一章咱们正式进入正题：**[第 01 章：别让 AI 乱改代码——用 OpenSpec 给 Vibe Coding 立规矩](./01-openspec-foundation.md)**！
