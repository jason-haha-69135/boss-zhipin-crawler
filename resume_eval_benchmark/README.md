# 简历解析与异常拦截评测基准 (`resume_eval_benchmark`)

本模块位于 `boss-zhipin-crawler/resume_eval_benchmark`，提供面向 [`CandidateProfileSchema`](../core/resume_parser.py)（阶段一结构化候选人画像）的完整评测基准数据集与自动化评测工具：

1. **Qualified Resume Dataset（25 份多格式全行业简历 + Ground Truth 标注）**：用于评测简历解析模型的字段提取准确率、隐式信息推断能力及 PII 敏感信息脱敏合规率。
2. **Disqualified Dataset（20 份边界与异常对抗样本 + 预期拦截错误码）**：用于评测系统在文件格式校验、体积限制（10MB 文件上限 / 20MB DOCX 解压上限）、文件损坏/伪造、非简历内容及 Prompt 注入攻击下的鲁棒性。

---

## 目录结构

```text
boss-zhipin-crawler/resume_eval_benchmark/
├── __init__.py
├── schema_and_validator.py        # CandidateProfileSchema 定义与多层文件/内容/PII安全校验器
├── qualified_data_specs.py        # 25 份全行业正向简历的原文与 Ground Truth 数据定义
├── file_renderers.py              # 多格式渲染引擎 (.pdf/.docx/.png/.jpg/.jpeg/.webp/.txt/.md)
├── generate_datasets.py           # 数据集一键重新生成脚本
├── evaluate_parser.py             # 自动化评测与自检脚本（支持 --live-gemini 实测 core.resume_parser）
└── dataset/
    ├── qualified/                 # 25 份合法简历文件（覆盖全部 8 种 ALLOWED_EXTENSIONS）
    ├── disqualified/              # 20 份异常与安全对抗样本文件
    ├── qualified_manifest.json    # 正向评测集 Manifest（含 Ground Truth 与 raw_pii_tokens）
    └── disqualified_manifest.json # 异常评测集 Manifest（含预期拦截阶段与错误码）
```

---

## 快速使用指南

### 1. 重新生成或扩展数据集

```bash
python3 resume_eval_benchmark/generate_datasets.py
```

### 2. 运行基准自检与安全拦截验证

```bash
python3 resume_eval_benchmark/evaluate_parser.py
```

### 3. 直接评测 `core/resume_parser.py` 中的 Gemini 解析服务

```bash
python3 resume_eval_benchmark/evaluate_parser.py --live-gemini
```
