# BOSS直聘 智能求职分析助手 (Conversational Agent & Visualization Web App)

基于 **Playwright (CDP 协议接管本地 Chrome)** + **FastAPI (SSE 实时流式推送)** + **Google Gemini (Pro / Flash / Flash-Lite)** + **Apache ECharts** 构建的对话式求职采集与六维可视化分析系统。

## 1. 目录结构

```text
boss-zhipin-crawler/
├── design/
│   ├── system_design.md                 # 完整系统架构设计方案 (Markdown)
│   └── boss_api_and_labels_reference.md # BOSS直聘 URL 过滤编码与 API 字段全集字典
├── core/
│   ├── __init__.py
│   ├── intent_parser.py                 # 自然语言求职意图解析器 (URL硬性参数 + 软性条件)
│   ├── boss_crawler.py                  # 两阶段爬虫引擎 (列表批量抓取 + Top 8 详情页完整JD补全)
│   └── gemini_analyzer.py               # Python 六维精确统计 + Gemini 深度洞察与匹配度评分
├── static/
│   ├── index.html                       # 对话式查询与可视化 Dashboard 单页前端
│   ├── styles.css                       # 响应式样式表
│   └── app.js                           # SSE 实时进度控制与 ECharts 六维图表渲染
├── output/                              # 自动导出的 Excel (.xlsx) 岗位明细表目录
├── app.py                               # FastAPI Web 服务主入口
├── crawl_boss_poc.py                    # 命令行版 PoC 采集脚本
├── start_chrome.sh                      # 启动带 9222 调试端口的独立 Chrome 脚本
└── requirements.txt                     # Python 依赖列表
```

## 2. 快速启动指南

### 第一步：启动调试模式 Chrome 并登录 BOSS直聘
```bash
cd /Users/yafan/boss-zhipin-crawler
./start_chrome.sh
```
> 在弹出的 Chrome 窗口中确认已登录 BOSS直聘（登录态会自动保存在 `.chrome_profile/` 中，后续无需重复扫码）。保持该 Chrome 窗口开启。

### 第二步：配置 Gemini API Key 并启动 Web 服务
您可以通过环境变量设置 GCP Gemini API Key，或者启动后直接在网页右上角输入框中粘贴：
```bash
cd /Users/yafan/boss-zhipin-crawler
source .venv/bin/activate

# 可选：通过环境变量配置 Gemini API Key
export GEMINI_API_KEY="您的_GCP_GEMINI_API_KEY"

# 启动 Web 服务
python app.py
```

### 第三步：打开浏览器使用对话式分析助手
在任意浏览器访问：
- **http://127.0.0.1:8000**

1. **选择模型**：在右上角切换 `Gemini 2.5 Pro`、`Gemini 2.5 Flash` 或 `Gemini 2.5 Flash-Lite`。
2. **选择采集深度**：支持 `快速 (5批/约75条)`、`标准 (10批/约150条)`、`全量 (30批/最高450条，遇底自动停止)`。
3. **输入自然语言查询**：例如 `"深圳的服装店面督导，月薪至少1w，周末要双休"`，点击 **开始采集与智能分析**。
4. **查看可视化结果**：
   - 实时进度条展示【意图解析 -> 阶段1列表批量采集 -> 阶段2 Top 8 候选岗位详情页完整JD抓取 -> Gemini 六维分析】。
   - 自动渲染 **综合匹配度仪表盘 (0-100分)**、**六维 ECharts 图表（所属行业、薪资分布、核心技能、经验与学历、公司规模与知名度、福利与双休作息）**、**Top 8 深度匹配岗位卡片**，并提供 **完整 Excel (.xlsx) 一键下载**。
