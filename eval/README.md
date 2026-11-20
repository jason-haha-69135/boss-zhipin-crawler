# 全链路评测工作台 (`eval/`)

本目录 (`boss-zhipin-crawler/eval/`) 提供 Stage 1 ~ Stage 5 全链路自动化评测、LLM-as-a-Judge 原子核验（默认裁判模型 `gemini-4-argon`）与历史评测批次归档能力。

## 目录结构

```text
eval/
├── eval_store.py                          # 统一三层评测协议注册表、数据集加载与历史 Run 归档存储
├── runs/                                  # 存放所有 Stage 每次评测运行的归档结果与最新快照
│   ├── latest_stage1_eval_report.json
│   ├── latest_stage2_eval_report.json
│   ├── run_stage1_profile_*.json
│   └── run_stage2_queries_*.json
├── dataset/                               # 按 Stage 独立划分的标准评测数据集
│   ├── stage1/
│   │   ├── qualified/                     # 9 份多模态合格简历正例 (.pdf/.docx/.jpg/.md)
│   │   ├── disqualified/                  # 9 份安全与格式拦截反例
│   │   ├── qualified_manifest.json
│   │   └── disqualified_manifest.json
│   ├── stage2/
│   │   └── stage2_qualified_manifest.json # Stage 2 候选人画像输入与基准锚点清单
│   ├── stage3/
│   │   └── stage3_intent_manifest.json
│   ├── stage4/
│   │   └── stage4_ranking_manifest.json
│   └── stage5/
│       └── stage5_analysis_manifest.json
├── stage1_eval/                           # Stage 1 独立评测脚本目录
│   ├── evaluate_stage1_parser.py          # Stage 1 简历多模态提取评测主入口
│   ├── llm_judge_stage1.py                # Stage 1 LLM-as-a-Judge (默认 gemini-4-argon)
│   ├── stage1_schema_validator.py         # Stage 1 Schema 与文件/PII 安全校验器
│   ├── generate_stage1_datasets.py        # Stage 1 数据集生成器
│   ├── stage1_file_renderers.py           # 多格式文件渲染器
│   └── stage1_qualified_specs.py          # 合格简历标准规格定义
├── stage2_eval/                           # Stage 2 独立评测脚本目录
│   ├── evaluate_stage2_queries.py         # Stage 2 10维搜索 Query 生成评测主入口
│   └── llm_judge_stage2.py                # Stage 2 LLM-as-a-Judge (默认 gemini-4-argon)
├── stage3_eval/                           # Stage 3 独立评测脚本目录
│   └── evaluate_stage3_intent.py
├── stage4_eval/                           # Stage 4 独立评测脚本目录
│   └── evaluate_stage4_ranking.py
└── stage5_eval/                           # Stage 5 独立评测脚本目录
    └── evaluate_stage5_analysis.py
```

## 快速运行命令

```bash
# 运行 Stage 1 评测（提取模型默认 gemini-3.8-flash，裁判模型默认 gemini-4-argon）
python eval/stage1_eval/evaluate_stage1_parser.py --live-gemini --llm-judge

# 运行 Stage 2 评测（生成模型默认 gemini-3.8-flash，裁判模型默认 gemini-4-argon）
python eval/stage2_eval/evaluate_stage2_queries.py
```
