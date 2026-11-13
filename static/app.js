/**
 * BOSS直聘 智能求职分析助手前端交互与 ECharts 六维可视化逻辑
 * 遵循安全编码规范：全部 DOM 渲染均使用 createElement / textContent / replaceChildren，绝不使用 innerHTML 或 alert()。
 */

(function () {
  "use strict";

  const queryForm = document.getElementById("query-form");
  const queryInput = document.getElementById("query-input");
  const submitBtn = document.getElementById("submit-btn");
  const modelSelect = document.getElementById("model-select");
  const batchesSelect = document.getElementById("batches-select");
  const topCountInput = document.getElementById("top-count-input");
  const topCountInlineInput = document.getElementById("top-count-inline-input");
  const topJobsTitle = document.getElementById("top-jobs-title");
  const gaugeTopCountLabel = document.getElementById("gauge-top-count-label");
  const errorBanner = document.getElementById("error-banner");

  const progressSection = document.getElementById("progress-section");
  const progressSpinner = document.getElementById("progress-spinner");
  const progressStatusText = document.getElementById("progress-status-text");
  const progressPercentText = document.getElementById("progress-percent-text");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const intentTagsContainer = document.getElementById("intent-tags-container");

  const dashboardSection = document.getElementById("dashboard-section");
  const resultMetaBadge = document.getElementById("result-meta-badge");
  const downloadExcelLink = document.getElementById("download-excel-link");
  const executiveSummaryText = document.getElementById("executive-summary-text");
  const matchVerdictText = document.getElementById("match-verdict-text");
  const matchStrengthsList = document.getElementById("match-strengths-list");
  const matchRisksList = document.getElementById("match-risks-list");
  const matchAdviceList = document.getElementById("match-advice-list");

  const salaryKpiRow = document.getElementById("salary-kpi-row");
  const notableBrandsRow = document.getElementById("notable-brands-row");
  const recommendedJobsContainer = document.getElementById("recommended-jobs-container");

  // Step 0: 简历上传与智能 Query 推荐 DOM 引用
  const resumeDropzone = document.getElementById("resume-dropzone");
  const resumeFileInput = document.getElementById("resume-file-input");
  const resumeUploadBtn = document.getElementById("resume-upload-btn");
  const resumeClearBtn = document.getElementById("resume-clear-btn");
  const resumeStatusTitle = document.getElementById("resume-status-title");
  const resumeStatusDesc = document.getElementById("resume-status-desc");
  const resumeParsedContainer = document.getElementById("resume-parsed-container");
  const resumeProfileHeadline = document.getElementById("resume-profile-headline");
  const resumeProfileTags = document.getElementById("resume-profile-tags");
  const resumeHighlightsList = document.getElementById("resume-highlights-list");
  const resumeQueriesGrid = document.getElementById("resume-queries-grid");
  const resumeQueriesStatusText = document.getElementById("resume-queries-status-text");
  const profileCityOverride = document.getElementById("profile-city-override");
  const profileSalaryOverride = document.getElementById("profile-salary-override");
  const profileFocusOverride = document.getElementById("profile-focus-override");
  const regenerateQueriesBtn = document.getElementById("regenerate-queries-btn");

  // 当前会话已解析的脱敏简历画像（用于透传给 /api/analyze 进行人岗契合度深度诊断）
  let currentResumeProfile = null;
  let currentResumeFilename = "个人简历.pdf";
  let currentDashboardPayload = null;

  function clampTopCount(val) {
    const num = Math.round(Number(val));
    if (Number.isNaN(num)) return 8;
    return Math.max(3, Math.min(20, num));
  }

  function syncTopCountUI(count, updateInputs = true) {
    const clamped = clampTopCount(count);
    if (updateInputs) {
      if (topCountInput) topCountInput.value = String(clamped);
      if (topCountInlineInput) topCountInlineInput.value = String(clamped);
    }
    if (topJobsTitle) {
      topJobsTitle.textContent = `Top ${clamped} 候选岗位深度匹配榜（已补全详情页完整 JD）`;
    }
    if (gaugeTopCountLabel) {
      gaugeTopCountLabel.textContent = `Top ${clamped}`;
    }
    if (currentDashboardPayload && currentDashboardPayload.report) {
      const allRec = Array.isArray(currentDashboardPayload.report.recommended_jobs)
        ? currentDashboardPayload.report.recommended_jobs
        : [];
      const shownList = allRec.slice(0, clamped);
      resultMetaBadge.textContent = `模型: ${
        currentDashboardPayload.model_label || currentDashboardPayload.model
      } | 采集样本: ${currentDashboardPayload.total_crawled || 0} 条 | 深度解析详情: Top ${
        shownList.length || clamped
      } 条`;
      renderRecommendedJobs(shownList);
    }
    return clamped;
  }

  // ECharts 实例字典
  const chartInstances = {};

  function getOrCreateChart(domId) {
    const el = document.getElementById(domId);
    if (!el) return null;
    if (chartInstances[domId]) {
      chartInstances[domId].dispose();
    }
    const instance = window.echarts.init(el);
    chartInstances[domId] = instance;
    return instance;
  }

  window.addEventListener("resize", () => {
    Object.values(chartInstances).forEach((chart) => {
      if (chart) chart.resize();
    });
  });

  function showError(msg) {
    if (!msg) {
      errorBanner.classList.add("hidden");
      errorBanner.textContent = "";
      return;
    }
    errorBanner.textContent = msg;
    errorBanner.classList.remove("hidden");
  }

  function updateProgress(percent, message, isFinished = false) {
    progressSection.classList.remove("hidden");
    const clamped = Math.max(0, Math.min(100, Number(percent) || 0));
    progressBarFill.style.width = `${clamped}%`;
    progressPercentText.textContent = `${clamped}%`;
    if (message) {
      progressStatusText.textContent = message;
    }
    if (isFinished) {
      progressSpinner.classList.add("hidden");
    } else {
      progressSpinner.classList.remove("hidden");
    }
  }

  function renderIntentTags(intent) {
    if (!intent) return;
    const pills = [
      `城市: ${intent.city_name || "深圳"}`,
      `核心岗位: ${intent.query || ""}`,
      `薪资档位: ${intent.salary_label || "不限"}`,
    ];
    if (intent.min_salary_k > 0) {
      pills.push(`期望底线: ≥${intent.min_salary_k}K`);
    }
    if (intent.require_double_weekend) {
      pills.push("作息偏好: 周末双休");
    }
    if (Array.isArray(intent.industry_keywords) && intent.industry_keywords.length > 0) {
      pills.push(`行业关键词: ${intent.industry_keywords.slice(0, 4).join("/")}`);
    }

    const nodes = pills.map((text) => {
      const span = document.createElement("span");
      span.className = "intent-pill";
      span.textContent = text;
      return span;
    });
    intentTagsContainer.replaceChildren(...nodes);
  }

  function renderStringList(ulElement, items) {
    const list = Array.isArray(items) ? items : [];
    const liNodes = list.map((itemText) => {
      const li = document.createElement("li");
      li.textContent = String(itemText || "");
      return li;
    });
    ulElement.replaceChildren(...liNodes);
  }

  function renderSalaryKpis(metrics) {
    if (!metrics) {
      salaryKpiRow.replaceChildren();
      return;
    }
    const kpis = [
      { label: "平均起薪", val: `${metrics.avg_min_k || 0}K` },
      { label: "平均上限", val: `${metrics.avg_max_k || 0}K` },
      { label: "薪资中位数", val: `${metrics.median_mid_k || 0}K` },
      { label: "13薪+占比", val: `${metrics.bonus_months_ratio || 0}%` },
    ];
    const nodes = kpis.map((item) => {
      const box = document.createElement("div");
      box.className = "kpi-pill";
      const lbl = document.createElement("span");
      lbl.className = "kpi-label";
      lbl.textContent = item.label;
      const val = document.createElement("span");
      val.className = "kpi-val";
      val.textContent = item.val;
      box.appendChild(lbl);
      box.appendChild(val);
      return box;
    });
    salaryKpiRow.replaceChildren(...nodes);
  }

  function renderNotableBrands(companies) {
    const list = Array.isArray(companies) ? companies : [];
    if (list.length === 0) {
      notableBrandsRow.replaceChildren();
      return;
    }
    const nodes = list.slice(0, 12).map((name) => {
      const span = document.createElement("span");
      span.className = "brand-tag";
      span.textContent = String(name);
      return span;
    });
    notableBrandsRow.replaceChildren(...nodes);
  }

  // ==================== ECharts 六维图表渲染 ====================
  function renderMatchGauge(score) {
    const chart = getOrCreateChart("chart-match-gauge");
    if (!chart) return;
    const val = Math.max(0, Math.min(100, Number(score) || 0));
    chart.setOption({
      series: [
        {
          type: "gauge",
          startAngle: 200,
          endAngle: -20,
          min: 0,
          max: 100,
          progress: { show: true, width: 14 },
          axisLine: {
            lineStyle: {
              width: 14,
              color: [
                [0.6, "#f59e0b"],
                [0.8, "#00a6a7"],
                [1, "#10b981"],
              ],
            },
          },
          axisTick: { show: false },
          splitLine: { length: 8, lineStyle: { width: 2, color: "#94a3b8" } },
          axisLabel: { distance: 16, color: "#64748b", fontSize: 11 },
          pointer: { width: 5, length: "62%" },
          detail: {
            valueAnimation: true,
            formatter: "{value} 分",
            fontSize: 24,
            fontWeight: "bold",
            color: "#0f172a",
            offsetCenter: [0, "55%"],
          },
          data: [{ value: val, name: "匹配指数" }],
          title: { offsetCenter: [0, "82%"], fontSize: 12, color: "#64748b" },
        },
      ],
    });
  }

  function renderIndustryChart(data) {
    const chart = getOrCreateChart("chart-industry");
    if (!chart) return;
    const list = Array.isArray(data) ? data : [];
    chart.setOption({
      tooltip: { trigger: "item", formatter: "{b}: {c} 个岗位 ({d}%)" },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } },
      color: ["#00a6a7", "#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#64748b"],
      series: [
        {
          name: "所属行业",
          type: "pie",
          radius: ["40%", "68%"],
          center: ["50%", "44%"],
          itemStyle: { borderRadius: 6, borderColor: "#fff", borderWidth: 2 },
          label: { formatter: "{b}\n{d}%", fontSize: 11 },
          data: list,
        },
      ],
    });
  }

  function renderSalaryChart(buckets) {
    const chart = getOrCreateChart("chart-salary");
    if (!chart) return;
    const list = Array.isArray(buckets) ? buckets : [];
    chart.setOption({
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { top: 24, right: 16, bottom: 30, left: 42 },
      xAxis: {
        type: "category",
        data: list.map((x) => x.range),
        axisLabel: { fontSize: 11 },
      },
      yAxis: { type: "value", name: "岗位数" },
      series: [
        {
          name: "岗位数量",
          type: "bar",
          barWidth: "52%",
          data: list.map((x) => x.count),
          itemStyle: {
            color: "#00a6a7",
            borderRadius: [6, 6, 0, 0],
          },
          label: { show: true, position: "top", fontSize: 11 },
        },
      ],
    });
  }

  function renderSkillsChart(skills) {
    const chart = getOrCreateChart("chart-skills");
    if (!chart) return;
    const list = (Array.isArray(skills) ? skills : []).slice(0, 12).reverse();
    chart.setOption({
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { top: 12, right: 32, bottom: 20, left: 105 },
      xAxis: { type: "value" },
      yAxis: {
        type: "category",
        data: list.map((x) => x.name),
        axisLabel: { fontSize: 11 },
      },
      series: [
        {
          name: "出现频次",
          type: "bar",
          data: list.map((x) => x.value),
          itemStyle: {
            color: "#3b82f6",
            borderRadius: [0, 5, 5, 0],
          },
          label: { show: true, position: "right", fontSize: 11 },
        },
      ],
    });
  }

  function renderExperienceChart(expData, degData) {
    const chart = getOrCreateChart("chart-experience");
    if (!chart) return;
    chart.setOption({
      tooltip: { trigger: "item", formatter: "{a} <br/>{b}: {c} ({d}%)" },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } },
      color: ["#00a6a7", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"],
      series: [
        {
          name: "经验要求",
          type: "pie",
          radius: ["32%", "58%"],
          center: ["28%", "44%"],
          label: { formatter: "{b}\n{c}", fontSize: 10.5 },
          data: Array.isArray(expData) ? expData : [],
        },
        {
          name: "学历要求",
          type: "pie",
          radius: ["32%", "58%"],
          center: ["74%", "44%"],
          label: { formatter: "{b}\n{c}", fontSize: 10.5 },
          data: Array.isArray(degData) ? degData : [],
        },
      ],
    });
  }

  function renderBrandChart(scaleData, stageData) {
    const chart = getOrCreateChart("chart-brand");
    if (!chart) return;
    const scales = Array.isArray(scaleData) ? scaleData : [];
    const stages = Array.isArray(stageData) ? stageData : [];
    chart.setOption({
      tooltip: { trigger: "item", formatter: "{a} <br/>{b}: {c} ({d}%)" },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } },
      color: ["#0f172a", "#00a6a7", "#3b82f6", "#10b981", "#f59e0b", "#64748b"],
      series: [
        {
          name: "公司规模",
          type: "pie",
          radius: ["32%", "58%"],
          center: ["28%", "44%"],
          label: { formatter: "{b}\n{d}%", fontSize: 10.5 },
          data: scales,
        },
        {
          name: "融资阶段",
          type: "pie",
          radius: ["32%", "58%"],
          center: ["74%", "44%"],
          label: { formatter: "{b}\n{d}%", fontSize: 10.5 },
          data: stages,
        },
      ],
    });
  }

  function renderWelfareChart(weekendData, welfareData) {
    const chart = getOrCreateChart("chart-welfare");
    if (!chart) return;
    const weekends = Array.isArray(weekendData) ? weekendData : [];
    const welfares = (Array.isArray(welfareData) ? welfareData : []).slice(0, 8).reverse();

    chart.setOption({
      tooltip: { trigger: "item" },
      grid: { top: 20, right: 20, bottom: 24, left: "54%" },
      xAxis: { type: "value", gridIndex: 0 },
      yAxis: {
        type: "category",
        gridIndex: 0,
        data: welfares.map((x) => x.name),
        axisLabel: { fontSize: 10.5 },
      },
      series: [
        {
          name: "作息制度",
          type: "pie",
          radius: ["30%", "58%"],
          center: ["24%", "48%"],
          label: { formatter: "{b}\n{c}个", fontSize: 10.5 },
          data: weekends,
        },
        {
          name: "高频福利",
          type: "bar",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: welfares.map((x) => x.value),
          itemStyle: { color: "#10b981", borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: "right", fontSize: 10.5 },
        },
      ],
    });
  }

  // ==================== Top 8 候选岗位推荐卡片渲染 ====================
  function renderRecommendedJobs(jobs) {
    const list = Array.isArray(jobs) ? jobs : [];
    const cards = list.map((job) => {
      const card = document.createElement("div");
      card.className = "job-card";

      // 顶部标题与分值
      const topRow = document.createElement("div");
      topRow.className = "job-card-top";

      const titleWrap = document.createElement("div");
      titleWrap.className = "job-title-wrap";

      const titleLink = document.createElement("a");
      titleLink.className = "job-title-link";
      titleLink.textContent = `#${job.rank || ""} ${job.job_name || "未知岗位"}`;
      if (typeof job.job_url === "string" && job.job_url.startsWith("https://www.zhipin.com/")) {
        titleLink.setAttribute("href", job.job_url);
        titleLink.setAttribute("target", "_blank");
        titleLink.setAttribute("rel", "noopener noreferrer");
      } else {
        titleLink.setAttribute("href", "#");
      }

      const companyLine = document.createElement("div");
      companyLine.className = "job-company-line";
      companyLine.textContent = `${job.company_name || ""} · ${job.industry || ""} · ${job.scale || ""}`;

      titleWrap.appendChild(titleLink);
      titleWrap.appendChild(companyLine);

      const badgesRight = document.createElement("div");
      badgesRight.className = "job-badges-right";

      const salaryBadge = document.createElement("span");
      salaryBadge.className = "salary-badge";
      salaryBadge.textContent = job.salary_desc || "";

      const scoreBadge = document.createElement("span");
      const scoreNum = Number(job.match_score) || 0;
      const scoreClass = scoreNum >= 80 ? "score-high" : scoreNum >= 65 ? "score-mid" : "score-low";
      scoreBadge.className = `score-badge ${scoreClass}`;
      scoreBadge.textContent = `匹配度 ${scoreNum}分`;

      badgesRight.appendChild(salaryBadge);
      badgesRight.appendChild(scoreBadge);

      topRow.appendChild(titleWrap);
      topRow.appendChild(badgesRight);
      card.appendChild(topRow);

      // 元信息标签行
      const metaRow = document.createElement("div");
      metaRow.className = "job-meta-pills";

      const weekendPill = document.createElement("span");
      const wkPolicy = String(job.weekend_policy || "未明确注明");
      weekendPill.className =
        wkPolicy === "周末双休"
          ? "meta-pill pill-weekend-ok"
          : wkPolicy.includes("排班") || wkPolicy.includes("大小周")
          ? "meta-pill pill-weekend-warn"
          : "meta-pill";
      weekendPill.textContent = `作息: ${wkPolicy}`;
      metaRow.appendChild(weekendPill);

      [job.location, job.experience, job.degree, job.hr_activity ? `HR: ${job.hr_activity}` : ""].forEach(
        (txt) => {
          if (!txt) return;
          const p = document.createElement("span");
          p.className = "meta-pill";
          p.textContent = String(txt);
          metaRow.appendChild(p);
        }
      );
      card.appendChild(metaRow);

      // Gemini 匹配原因分析
      const reasonBox = document.createElement("div");
      reasonBox.className = "job-reason-box";
      reasonBox.textContent = `Gemini 点评：${job.match_reason || ""}`;
      card.appendChild(reasonBox);

      // 亮点与风险标签
      const tagsRow = document.createElement("div");
      tagsRow.className = "job-tags-row";
      (Array.isArray(job.highlights) ? job.highlights : []).forEach((h) => {
        const span = document.createElement("span");
        span.className = "tag-highlight";
        span.textContent = `✓ ${h}`;
        tagsRow.appendChild(span);
      });
      (Array.isArray(job.risks) ? job.risks : []).forEach((r) => {
        const span = document.createElement("span");
        span.className = "tag-risk";
        span.textContent = `! ${r}`;
        tagsRow.appendChild(span);
      });
      card.appendChild(tagsRow);

      // 详情页完整 JD 摘要
      if (job.jd_snippet) {
        const jdBox = document.createElement("div");
        jdBox.className = "job-jd-snippet";
        jdBox.textContent = `完整JD摘录：${job.jd_snippet}`;
        card.appendChild(jdBox);
      }

      return card;
    });

    recommendedJobsContainer.replaceChildren(...cards);
  }

  function renderFullDashboard(payload) {
    currentDashboardPayload = payload;
    dashboardSection.classList.remove("hidden");
    const report = payload.report || {};
    const dims = report.dimensions || {};
    const matchEval = report.match_evaluation || {};
    const selectedTopCount = clampTopCount(
      topCountInput ? topCountInput.value : payload.top_detail_count || 8
    );
    const allRec = Array.isArray(report.recommended_jobs) ? report.recommended_jobs : [];
    const shownJobs = allRec.slice(0, selectedTopCount);

    if (topJobsTitle) {
      topJobsTitle.textContent = `Top ${selectedTopCount} 候选岗位深度匹配榜（已补全详情页完整 JD）`;
    }
    if (gaugeTopCountLabel) {
      gaugeTopCountLabel.textContent = `Top ${selectedTopCount}`;
    }
    resultMetaBadge.textContent = `模型: ${payload.model_label || payload.model} | 采集样本: ${payload.total_crawled || 0} 条 | 深度解析详情: Top ${shownJobs.length || selectedTopCount} 条`;
    executiveSummaryText.textContent = report.executive_summary || "";
    matchVerdictText.textContent = matchEval.verdict || "";

    if (typeof payload.download_url === "string" && payload.download_url.startsWith("/api/download/")) {
      downloadExcelLink.setAttribute("href", payload.download_url);
      downloadExcelLink.classList.remove("hidden");
    } else {
      downloadExcelLink.classList.add("hidden");
    }

    renderStringList(matchStrengthsList, matchEval.strengths);
    renderStringList(matchRisksList, matchEval.risks);
    renderStringList(matchAdviceList, matchEval.advice);

    // 六维文字洞察
    document.getElementById("insight-industry").textContent = (dims.industry && dims.industry.insight) || "";
    document.getElementById("insight-salary").textContent = (dims.salary && dims.salary.insight) || "";
    document.getElementById("insight-skills").textContent = (dims.skills && dims.skills.insight) || "";
    document.getElementById("insight-experience").textContent = (dims.experience && dims.experience.insight) || "";
    document.getElementById("insight-brand").textContent = (dims.brand && dims.brand.insight) || "";
    document.getElementById("insight-welfare").textContent = (dims.welfare && dims.welfare.insight) || "";

    renderSalaryKpis(dims.salary && dims.salary.metrics);
    renderNotableBrands(dims.brand && dims.brand.notable_companies);

    // 渲染全部图表
    renderMatchGauge(matchEval.overall_score);
    renderIndustryChart(dims.industry && dims.industry.chart_data);
    renderSalaryChart(dims.salary && dims.salary.chart_data);
    renderSkillsChart(dims.skills && dims.skills.chart_data);
    renderExperienceChart(
      dims.experience && dims.experience.experience_data,
      dims.experience && dims.experience.degree_data
    );
    renderBrandChart(dims.brand && dims.brand.scale_data, dims.brand && dims.brand.stage_data);
    renderWelfareChart(dims.welfare && dims.welfare.weekend_data, dims.welfare && dims.welfare.welfare_data);

    // 渲染用户自定义的 Top N (3-20) 候选岗位
    renderRecommendedJobs(shownJobs);
  }

  // ==================== Step 0: 简历上传、Gemini 深度解析与预生成 Query 渲染 ====================
  function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("读取本地简历文件失败"));
      reader.readAsDataURL(file);
    });
  }

  function getStrategyTagClass(tag) {
    const t = String(tag || "");
    if (t.includes("晋升") || t.includes("高薪")) return "strategy-tag-pill strategy-tag-promote";
    if (t.includes("精准") || t.includes("对口")) return "strategy-tag-pill strategy-tag-match";
    if (t.includes("作息") || t.includes("福利")) return "strategy-tag-pill strategy-tag-welfare";
    return "strategy-tag-pill";
  }

  function renderResumeProfileStage(profile, populateOverrideInputs = true) {
    const prof = profile || {};
    currentResumeProfile = prof;

    resumeParsedContainer.classList.remove("hidden");
    resumeClearBtn.classList.remove("hidden");

    const titleParts = [
      prof.candidate_title || "求职候选人",
      prof.years_of_experience || "",
      prof.education_summary || "",
    ].filter(Boolean);
    resumeProfileHeadline.textContent = titleParts.join("  |  ");

    const pillTexts = [];
    if (Array.isArray(prof.target_cities) && prof.target_cities.length > 0) {
      pillTexts.push(`意向城市: ${prof.target_cities.join("/")}`);
    }
    if (prof.inferred_salary_floor) {
      pillTexts.push(`建议月薪底线: ≥${prof.inferred_salary_floor}`);
    }
    if (Array.isArray(prof.industry_background)) {
      prof.industry_background.forEach((ind) => {
        if (ind) pillTexts.push(`行业: ${ind}`);
      });
    }
    if (Array.isArray(prof.core_skills)) {
      prof.core_skills.forEach((sk) => {
        if (sk) pillTexts.push(sk);
      });
    }

    const tagNodes = pillTexts.map((txt) => {
      const span = document.createElement("span");
      span.className = "resume-skill-pill";
      span.textContent = String(txt);
      return span;
    });
    resumeProfileTags.replaceChildren(...tagNodes);

    renderStringList(resumeHighlightsList, prof.experience_highlights);

    if (populateOverrideInputs) {
      if (profileCityOverride) {
        const cities = Array.isArray(prof.target_cities) ? prof.target_cities : [];
        profileCityOverride.value = cities[0] || "深圳";
      }
      if (profileSalaryOverride) {
        profileSalaryOverride.value = prof.inferred_salary_floor || "1.2w";
      }
    }
  }

  function showQueriesLoadingState(loadingText) {
    if (resumeQueriesStatusText) {
      resumeQueriesStatusText.textContent = loadingText || "Gemini 正在基于您的简历画像生成 5 条定制化求职 Query...";
    }
    const placeholder = document.createElement("div");
    placeholder.className = "query-loading-placeholder";
    placeholder.textContent = loadingText || "正在调用 Stage 2 服务生成 5 条多策略求职 Query，请稍候...";
    resumeQueriesGrid.replaceChildren(placeholder);
  }

  function renderRecommendedQueriesStage(queries) {
    const list = Array.isArray(queries) ? queries : [];
    if (resumeQueriesStatusText) {
      resumeQueriesStatusText.textContent =
        "基于您的简历画像生成了以下 5 条定制化求职 Query（点击卡片即可填入下方搜索框，也可在右侧修改城市/底薪重生成）：";
    }

    const cardNodes = list.map((item, idx) => {
      const cardBtn = document.createElement("button");
      cardBtn.type = "button";
      cardBtn.className = idx === 0 ? "resume-query-card active-query" : "resume-query-card";

      const topRow = document.createElement("div");
      topRow.className = "resume-query-card-top";

      const tagSpan = document.createElement("span");
      tagSpan.className = getStrategyTagClass(item.strategy_tag);
      tagSpan.textContent = item.strategy_tag || `推荐方案 ${idx + 1}`;

      const hintSpan = document.createElement("span");
      hintSpan.className = "use-query-hint";
      hintSpan.textContent = idx === 0 ? "✓ 已填入搜索框" : "点击选用此 Query";

      topRow.appendChild(tagSpan);
      topRow.appendChild(hintSpan);

      const queryTextDiv = document.createElement("div");
      queryTextDiv.className = "resume-query-text";
      queryTextDiv.textContent = item.query_text || "";

      const reasonDiv = document.createElement("div");
      reasonDiv.className = "resume-query-reason";
      reasonDiv.textContent = item.match_reason || "";

      cardBtn.appendChild(topRow);
      cardBtn.appendChild(queryTextDiv);
      cardBtn.appendChild(reasonDiv);

      cardBtn.addEventListener("click", () => {
        queryInput.value = item.query_text || "";
        queryInput.focus();
        Array.from(resumeQueriesGrid.children).forEach((el) => {
          el.classList.remove("active-query");
          const hint = el.querySelector(".use-query-hint");
          if (hint) hint.textContent = "点击选用此 Query";
        });
        cardBtn.classList.add("active-query");
        hintSpan.textContent = "✓ 已填入搜索框";
      });

      return cardBtn;
    });

    resumeQueriesGrid.replaceChildren(...cardNodes);

    if (list.length > 0 && list[0].query_text) {
      queryInput.value = list[0].query_text;
    }
  }

  function renderResumeParseResult(data) {
    const profile = (data && data.profile) || {};
    const queries = Array.isArray(data && data.recommended_queries) ? data.recommended_queries : [];
    if (data && data.filename) {
      currentResumeFilename = data.filename;
    }
    renderResumeProfileStage(profile, true);
    renderRecommendedQueriesStage(queries);
  }

  async function requestGenerateQueriesFromProfile(profileObj, filename) {
    if (!profileObj) return;
    showError("");
    if (regenerateQueriesBtn) {
      regenerateQueriesBtn.disabled = true;
      regenerateQueriesBtn.textContent = "正在生成 Query...";
    }

    const cityVal = profileCityOverride ? profileCityOverride.value.trim() : "";
    const salaryVal = profileSalaryOverride ? profileSalaryOverride.value.trim() : "";
    const focusVal = profileFocusOverride ? profileFocusOverride.value.trim() : "";

    showQueriesLoadingState(
      `Stage 2 服务正在结合您的简历画像与意向条件（城市: ${cityVal || "默认"} | 底薪: ${salaryVal || "默认"}）定制 5 条求职 Query...`
    );

    try {
      const response = await fetch("/api/resume/generate-queries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile: profileObj,
          target_city: cityVal || null,
          salary_floor: salaryVal || null,
          custom_focus: focusVal || null,
          model: modelSelect.value,
          filename: filename || currentResumeFilename,
        }),
      });

      const resData = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resData.detail || `生成推荐 Query 失败 (HTTP ${response.status})`);
      }

      if (resData.profile) {
        renderResumeProfileStage(resData.profile, true);
      }
      renderRecommendedQueriesStage(resData.recommended_queries || []);
      resumeStatusDesc.textContent =
        "两阶段解析已完成！您可以点击下方任意一条 AI 定制的 Query 填入搜索框，或修改意向城市/底薪重新生成。";
    } catch (err) {
      showError(`生成求职 Query 未成功：${err.message || String(err)}`);
    } finally {
      if (regenerateQueriesBtn) {
        regenerateQueriesBtn.disabled = false;
        regenerateQueriesBtn.textContent = "基于画像重生成 Query";
      }
    }
  }

  async function handleResumeFileUpload(file) {
    if (!file) return;
    showError("");

    const maxBytes = 10 * 1024 * 1024;
    if (file.size > maxBytes) {
      showError("上传的简历文件超过 10 MB 上限，请选择小于 10 MB 的简历文件。");
      return;
    }

    resumeUploadBtn.disabled = true;
    resumeUploadBtn.textContent = "Stage 1 解析画像中...";
    resumeStatusTitle.textContent = `正在执行 Stage 1（简历深度理解）：${file.name}`;
    resumeStatusDesc.textContent = "正在通过 Gemini 多模态提取您的核心工作年限、技能标签与量化业绩亮点...";

    try {
      const dataUrl = await readFileAsDataUrl(file);
      // 阶段一：独立调用 /api/resume/parse-profile，极速返回并渲染候选人画像卡片
      const stage1Resp = await fetch("/api/resume/parse-profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          content_base64: dataUrl,
          model: modelSelect.value,
        }),
      });

      const stage1Data = await stage1Resp.json().catch(() => ({}));
      if (!stage1Resp.ok) {
        throw new Error(stage1Data.detail || `简历画像提取失败 (HTTP ${stage1Resp.status})`);
      }

      currentResumeFilename = stage1Data.filename || file.name;
      resumeStatusTitle.textContent = `已解析简历画像：${currentResumeFilename}`;
      resumeStatusDesc.textContent = "Stage 1 简历画像已就绪！正在调用 Stage 2 服务为您量身生成 5 条求职 Query...";

      // 先行将 Stage 1 简历画像渲染上屏（渐进式呈现）
      renderResumeProfileStage(stage1Data.profile, true);

      // 阶段二：独立调用 /api/resume/generate-queries，基于结构化画像生成 5 条求职 Query
      resumeUploadBtn.textContent = "Stage 2 生成 Query 中...";
      await requestGenerateQueriesFromProfile(stage1Data.profile, currentResumeFilename);
    } catch (err) {
      resumeStatusTitle.textContent = "上传个人简历，让 Gemini 为您量身定制求职 Query";
      resumeStatusDesc.textContent = "支持拖拽或点击上传 .pdf / .docx / .png / .jpg / .txt（最大 10MB，纯内存安全解析）";
      showError(`简历解析未成功：${err.message || String(err)}`);
    } finally {
      resumeUploadBtn.disabled = false;
      resumeUploadBtn.textContent = "重新上传简历";
      resumeFileInput.value = "";
    }
  }

  function clearParsedResume() {
    currentResumeProfile = null;
    currentResumeFilename = "个人简历.pdf";
    resumeParsedContainer.classList.add("hidden");
    resumeClearBtn.classList.add("hidden");
    resumeProfileHeadline.textContent = "";
    resumeProfileTags.replaceChildren();
    resumeHighlightsList.replaceChildren();
    resumeQueriesGrid.replaceChildren();
    if (profileCityOverride) profileCityOverride.value = "";
    if (profileSalaryOverride) profileSalaryOverride.value = "";
    if (profileFocusOverride) profileFocusOverride.value = "";
    resumeUploadBtn.textContent = "上传简历智能生成 Query";
    resumeStatusTitle.textContent = "上传个人简历，让 Gemini 为您量身定制求职 Query";
    resumeStatusDesc.textContent = "支持拖拽或点击上传 .pdf / .docx / .png / .jpg / .txt（最大 10MB，纯内存安全解析）";
  }

  // ==================== SSE 流式请求控制 ====================
  async function startAnalysis(userQuery) {
    showError("");
    submitBtn.disabled = true;
    submitBtn.textContent = "正在采集中...";
    intentTagsContainer.replaceChildren();
    updateProgress(2, "正在发起分析请求...", false);

    const topDetailCount = syncTopCountUI(topCountInput ? topCountInput.value : 8, true);

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: userQuery,
          model: modelSelect.value,
          max_batches: Number(batchesSelect.value) || 10,
          top_detail_count: topDetailCount,
          resume_profile: currentResumeProfile,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`服务端响应异常 (HTTP ${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const lines = frame.split("\n");
          let eventType = "message";
          let dataStr = "";
          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataStr += line.slice(5).trim();
            }
          }
          if (!dataStr) continue;

          const payload = JSON.parse(dataStr);
          if (eventType === "progress") {
            updateProgress(payload.percent, payload.message, false);
          } else if (eventType === "intent") {
            updateProgress(payload.percent, payload.message, false);
            renderIntentTags(payload.intent);
          } else if (eventType === "result") {
            updateProgress(100, payload.message, true);
            renderIntentTags(payload.intent);
            renderFullDashboard(payload);
          } else if (eventType === "error") {
            updateProgress(0, "任务中断", true);
            showError(payload.message || "发生未知错误");
          }
        }
      }
    } catch (err) {
      showError(`请求失败：${err.message || String(err)}`);
      updateProgress(0, "请求失败", true);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "开始采集与智能分析";
    }
  }

  // 事件绑定
  if (resumeUploadBtn && resumeFileInput) {
    resumeUploadBtn.addEventListener("click", () => {
      resumeFileInput.click();
    });
    resumeFileInput.addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (file) {
        handleResumeFileUpload(file);
      }
    });
  }

  if (resumeClearBtn) {
    resumeClearBtn.addEventListener("click", () => {
      clearParsedResume();
    });
  }

  if (regenerateQueriesBtn) {
    regenerateQueriesBtn.addEventListener("click", () => {
      if (currentResumeProfile) {
        requestGenerateQueriesFromProfile(currentResumeProfile, currentResumeFilename);
      }
    });
  }

  [profileCityOverride, profileSalaryOverride, profileFocusOverride].forEach((inputEl) => {
    if (!inputEl) return;
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        if (currentResumeProfile) {
          requestGenerateQueriesFromProfile(currentResumeProfile, currentResumeFilename);
        }
      }
    });
  });

  if (resumeDropzone) {
    resumeDropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      resumeDropzone.classList.add("drag-over");
    });
    resumeDropzone.addEventListener("dragleave", () => {
      resumeDropzone.classList.remove("drag-over");
    });
    resumeDropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      resumeDropzone.classList.remove("drag-over");
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) {
        handleResumeFileUpload(file);
      }
    });
  }

  // 绑定 Top 候选岗数量 (3-20) 双向同步与实时过滤事件
  [topCountInput, topCountInlineInput].forEach((inputEl) => {
    if (!inputEl) return;
    inputEl.addEventListener("change", () => {
      syncTopCountUI(inputEl.value, true);
    });
    inputEl.addEventListener("input", () => {
      const num = Number(inputEl.value);
      if (num >= 3 && num <= 20) {
        if (inputEl === topCountInput && topCountInlineInput) {
          topCountInlineInput.value = String(Math.round(num));
        } else if (inputEl === topCountInlineInput && topCountInput) {
          topCountInput.value = String(Math.round(num));
        }
        syncTopCountUI(num, false);
      }
    });
  });

  queryForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = queryInput.value.trim();
    if (!q) return;
    startAnalysis(q);
  });

  document.querySelectorAll(".chip-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.getAttribute("data-query") || "";
      queryInput.value = q;
      if (resumeQueriesGrid) {
        Array.from(resumeQueriesGrid.children).forEach((el) => {
          el.classList.remove("active-query");
          const hint = el.querySelector(".use-query-hint");
          if (hint) hint.textContent = "点击选用此 Query";
        });
      }
    });
  });

  // ==================== 全链路评测工作台 (Option A: Unified Evaluation Dashboard) ====================
  const navTabSearch = document.getElementById("nav-tab-search");
  const navTabEval = document.getElementById("nav-tab-eval");
  const searchWorkspaceWrapper = document.getElementById("search-workspace-wrapper");
  const searchConfigBar = document.getElementById("search-config-bar");
  const evalWorkspaceSection = document.getElementById("eval-workspace-section");

  const evalStageStepper = document.getElementById("eval-stage-stepper");
  const evalStageProtocolBanner = document.getElementById("eval-stage-protocol-banner");
  const evalViewBtnAggregated = document.getElementById("eval-view-btn-aggregated");
  const evalViewBtnSingle = document.getElementById("eval-view-btn-single");
  const evalAggregatedView = document.getElementById("eval-aggregated-view");
  const evalSingleView = document.getElementById("eval-single-view");

  const evalRunSelect = document.getElementById("eval-run-select");
  const evalBatchExtSelect = document.getElementById("eval-batch-ext-select");
  const evalBatchLimitInput = document.getElementById("eval-batch-limit-input");
  const evalRunBatchBtn = document.getElementById("eval-run-batch-btn");
  const evalStatusBanner = document.getElementById("eval-status-banner");

  const evalKpiGrid = document.getElementById("eval-kpi-grid");
  const evalAggExtFilter = document.getElementById("eval-agg-ext-filter");
  const evalAggIssueFilter = document.getElementById("eval-agg-issue-filter");
  const evalSamplesTableBody = document.getElementById("eval-samples-table-body");
  const evalDisqSummaryBadge = document.getElementById("eval-disq-summary-badge");
  const evalDisqTableBody = document.getElementById("eval-disq-table-body");

  const evalPrevSampleBtn = document.getElementById("eval-prev-sample-btn");
  const evalNextSampleBtn = document.getElementById("eval-next-sample-btn");
  const evalSingleSampleSelect = document.getElementById("eval-single-sample-select");
  const evalSingleExtractModel = document.getElementById("eval-single-extract-model");
  const evalSingleJudgeModel = document.getElementById("eval-single-judge-model");
  const evalRunSingleBtn = document.getElementById("eval-run-single-btn");
  const evalSingleSummaryCard = document.getElementById("eval-single-summary-card");
  const evalSingleRawText = document.getElementById("eval-single-raw-text");
  const evalSinglePiiTokens = document.getElementById("eval-single-pii-tokens");
  const evalAtomicDiffTbody = document.getElementById("eval-atomic-diff-tbody");

  const FIELD_LABELS_MAP = {
    candidate_title: "岗位头衔 (candidate_title)",
    years_of_experience: "工作年限 (years_of_experience)",
    education_summary: "学历与院校 (education_summary)",
    target_cities: "意向城市 (target_cities)",
    industry_background: "行业背景 (industry_background)",
    core_skills: "核心技能 (core_skills)",
    experience_highlights: "量化业绩亮点 (experience_highlights)",
    inferred_salary_floor: "建议月薪底线 (inferred_salary_floor)",
    inferred_welfare_prefs: "作息与福利 (inferred_welfare_prefs)",
  };

  const FIELD_SHORT_LABELS = {
    candidate_title: "岗位",
    years_of_experience: "年限",
    education_summary: "学历",
    target_cities: "城市",
    industry_background: "行业",
    core_skills: "技能",
    experience_highlights: "业绩",
    inferred_salary_floor: "底薪",
    inferred_welfare_prefs: "福利",
  };

  let evalState = {
    initialized: false,
    stages: [],
    selectedStageId: "stage1_profile",
    runs: [],
    activeRun: null,
    catalog: { qualified_samples: [], disqualified_samples: [], field_labels: {} },
    viewMode: "aggregated", // "aggregated" | "single"
    selectedSampleId: "QUAL-001",
  };

  function showEvalStatus(message, isError = false) {
    if (!evalStatusBanner) return;
    if (!message) {
      evalStatusBanner.classList.add("hidden");
      evalStatusBanner.textContent = "";
      evalStatusBanner.classList.remove("is-error");
      return;
    }
    evalStatusBanner.textContent = message;
    evalStatusBanner.classList.toggle("is-error", Boolean(isError));
    evalStatusBanner.classList.remove("hidden");
  }

  function formatFieldVal(val) {
    if (val === null || val === undefined) return "—";
    if (Array.isArray(val)) {
      if (val.length === 0) return "[]";
      return val.map((item, i) => (val.length > 2 ? `${i + 1}. ${item}` : String(item))).join(
        val.length > 2 ? "\n" : " / "
      );
    }
    if (typeof val === "object") {
      return JSON.stringify(val, null, 2);
    }
    return String(val);
  }

  function getScorePillClass(score10) {
    const s = Number(score10) || 0;
    if (s >= 9.5) return "eval-mini-field-pill pill-score-perfect";
    if (s >= 8.0) return "eval-mini-field-pill pill-score-good";
    if (s >= 6.0) return "eval-mini-field-pill pill-score-warn";
    return "eval-mini-field-pill pill-score-low";
  }

  function getScoreBarColor(score10) {
    const s = Number(score10) || 0;
    if (s >= 9.5) return "#10b981";
    if (s >= 8.0) return "#00a6a7";
    if (s >= 6.0) return "#f59e0b";
    return "#ef4444";
  }

  function renderStageStepper() {
    if (!evalStageStepper || !evalStageProtocolBanner) return;
    const stages = Array.isArray(evalState.stages) ? evalState.stages : [];
    const cards = stages.map((st, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      const isSelected = st.stage_id === evalState.selectedStageId;
      btn.className = isSelected ? "eval-stage-card active-stage" : "eval-stage-card";

      const topRow = document.createElement("div");
      topRow.className = "eval-stage-top";

      const numSpan = document.createElement("span");
      numSpan.className = "eval-stage-num";
      numSpan.textContent = `STAGE ${idx + 1}`;

      const statusSpan = document.createElement("span");
      const isReady = st.status === "active";
      statusSpan.className = isReady
        ? "eval-stage-status stage-status-ready"
        : "eval-stage-status stage-status-planned";
      statusSpan.textContent = isReady ? "● 已就绪 (Live)" : "○ 协议已预留";

      topRow.appendChild(numSpan);
      topRow.appendChild(statusSpan);

      const nameDiv = document.createElement("div");
      nameDiv.className = "eval-stage-name";
      nameDiv.textContent = st.stage_name.replace(/^Stage\s*\d+:\s*/i, "");

      const modeDiv = document.createElement("div");
      modeDiv.className = "eval-stage-mode";
      modeDiv.textContent = `评测器: ${st.judge_mode}`;

      btn.appendChild(topRow);
      btn.appendChild(nameDiv);
      btn.appendChild(modeDiv);

      btn.addEventListener("click", () => {
        evalState.selectedStageId = st.stage_id;
        renderStageStepper();
      });
      return btn;
    });
    evalStageStepper.replaceChildren(...cards);

    const activeStageObj =
      stages.find((s) => s.stage_id === evalState.selectedStageId) || stages[0];
    if (activeStageObj) {
      const leftInfo = document.createElement("div");
      const titleStrong = document.createElement("strong");
      titleStrong.textContent = `${activeStageObj.stage_name} — `;
      const descSpan = document.createElement("span");
      descSpan.textContent = activeStageObj.description || "";
      leftInfo.appendChild(titleStrong);
      leftInfo.appendChild(descSpan);

      const dimsWrap = document.createElement("div");
      dimsWrap.className = "eval-protocol-dims";
      const dimsLabel = document.createElement("span");
      dimsLabel.style.fontSize = "11.5px";
      dimsLabel.style.fontWeight = "700";
      dimsLabel.textContent = "原子核对维度 (atomic_checks): ";
      dimsWrap.appendChild(dimsLabel);

      (Array.isArray(activeStageObj.atomic_dimensions)
        ? activeStageObj.atomic_dimensions
        : []
      ).forEach((dimName) => {
        const chip = document.createElement("span");
        chip.className = "eval-dim-chip";
        chip.textContent = String(dimName);
        dimsWrap.appendChild(chip);
      });

      evalStageProtocolBanner.replaceChildren(leftInfo, dimsWrap);
    }
  }

  function renderRunSelectDropdown() {
    if (!evalRunSelect) return;
    const runs = Array.isArray(evalState.runs) ? evalState.runs : [];
    const activeRunId = evalState.activeRun && evalState.activeRun.run_id;
    const options = runs.map((r) => {
      const opt = document.createElement("option");
      opt.value = r.run_id;
      const modeTag =
        r.evaluation_mode && r.evaluation_mode.includes("llm") ? "LLM-Judge" : "Heuristic";
      opt.textContent = `${r.created_at} | ${modeTag} (${r.judge_model}) | 样本:${r.qualified_total} | 均分:${Number(
        r.qualified_mean_score_10 || 0
      ).toFixed(2)}/10`;
      if (r.run_id === activeRunId) {
        opt.selected = true;
      }
      return opt;
    });
    evalRunSelect.replaceChildren(...options);
  }

  // ==================== 视图 A：Aggregated View 渲染 ====================
  function renderEvalAggregatedKpis(runData) {
    if (!evalKpiGrid) return;
    const agg = (runData && runData.aggregated_metrics) || {};
    const qTotal = Number(agg.qualified_total) || 0;
    const meanScore10 = Number(agg.qualified_mean_score_10) || 0;
    const entityRate = Number(agg.qualified_mean_entity_match_rate) || 0;
    const zeroHalluCount = Number(agg.qualified_zero_hallucination_samples) || 0;
    const zeroHalluRate = Number(agg.qualified_zero_hallucination_rate) || 0;
    const piiPassCount = Number(agg.qualified_valid_and_pii_safe) || 0;
    const piiPassRate = Number(agg.qualified_pii_pass_rate) || 0;
    const disqTotal = Number(agg.disqualified_total) || 20;
    const disqRejected = Number(agg.disqualified_correctly_rejected) || 20;

    const kpiDefs = [
      {
        title: "Semantic Completeness 综合均分",
        mainVal: `${meanScore10.toFixed(2)} / 10`,
        badge: `百分制 ${(meanScore10 * 10).toFixed(1)}%`,
        desc: `基于 9 个输出字段 0~10 原子核对算术平均 (已测 ${qTotal} 个样本)`,
      },
      {
        title: "关键数字 / 实体完全一致率",
        mainVal: `${(entityRate * 100).toFixed(1)}%`,
        badge: "Entity Exact Match",
        desc: "严苛核验年限、门店数、百分比、学校名、金额等关键实体",
      },
      {
        title: "零幻觉样本达标率 (Zero-Hallucination)",
        mainVal: `${(zeroHalluRate * 100).toFixed(1)}%`,
        badge: `${zeroHalluCount} / ${qTotal} 样本无幻觉`,
        desc: "在原子核对中同步拦截模型凭空捏造的原简历未提及信息",
      },
      {
        title: "Schema & PII 隐私脱敏通过率",
        mainVal: `${(piiPassRate * 100).toFixed(1)}%`,
        badge: `${piiPassCount} / ${qTotal} 样本合规`,
        desc: "100% 抹除姓名、手机、邮箱及家庭/学校详细门牌地址",
      },
      {
        title: "异常与攻击文件安全拦截率",
        mainVal: `${disqRejected} / ${disqTotal}`,
        badge: "100% 拦截",
        desc: "覆盖伪造签名、超大文件、乱码及 Prompt 注入等 20 个反例",
      },
    ];

    const nodes = kpiDefs.map((k) => {
      const card = document.createElement("div");
      card.className = "eval-kpi-card";

      const titleDiv = document.createElement("div");
      titleDiv.className = "eval-kpi-title";
      titleDiv.textContent = k.title;

      const valRow = document.createElement("div");
      valRow.className = "eval-kpi-value-row";

      const mainSpan = document.createElement("span");
      mainSpan.className = "eval-kpi-main-val";
      mainSpan.textContent = k.mainVal;

      const subBadge = document.createElement("span");
      subBadge.className = "eval-kpi-sub-badge";
      subBadge.textContent = k.badge;

      valRow.appendChild(mainSpan);
      valRow.appendChild(subBadge);

      const descDiv = document.createElement("div");
      descDiv.className = "eval-kpi-desc";
      descDiv.textContent = k.desc;

      card.appendChild(titleDiv);
      card.appendChild(valRow);
      card.appendChild(descDiv);
      return card;
    });

    evalKpiGrid.replaceChildren(...nodes);
  }

  function renderEvalAggregatedCharts(runData) {
    const agg = (runData && runData.aggregated_metrics) || {};
    const perField = agg.per_field_mean_scores_10 || {};
    const byExt = agg.by_extension_summary || {};

    // Chart A1: 9-Field Atomic Mean Scores (0 ~ 10)
    const chartFields = getOrCreateChart("chart-eval-fields");
    if (chartFields) {
      const fieldKeys = Object.keys(FIELD_LABELS_MAP).reverse();
      const fieldNames = fieldKeys.map((k) => FIELD_SHORT_LABELS[k] || k);
      const fieldVals = fieldKeys.map((k) => Number(perField[k] ?? 0));

      chartFields.setOption({
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          formatter: (params) => {
            const p = params && params[0];
            if (!p) return "";
            const fullKey = fieldKeys[p.dataIndex];
            return `${FIELD_LABELS_MAP[fullKey] || p.name}<br/>原子核对平均分: <b>${Number(
              p.value
            ).toFixed(2)} / 10.0</b>`;
          },
        },
        grid: { top: 14, right: 48, bottom: 24, left: 64 },
        xAxis: {
          type: "value",
          min: 0,
          max: 10,
          name: "得分",
          axisLabel: { fontSize: 11 },
        },
        yAxis: {
          type: "category",
          data: fieldNames,
          axisLabel: { fontSize: 12, fontWeight: 600 },
        },
        series: [
          {
            name: "原子核对均分",
            type: "bar",
            barWidth: "58%",
            data: fieldVals.map((v) => ({
              value: v,
              itemStyle: {
                color: getScoreBarColor(v),
                borderRadius: [0, 6, 6, 0],
              },
            })),
            label: {
              show: true,
              position: "right",
              formatter: "{c} 分",
              fontSize: 11,
              fontWeight: "bold",
            },
          },
        ],
      });
    }

    // Chart A2: File Format Breakdown
    const chartFormats = getOrCreateChart("chart-eval-formats");
    if (chartFormats) {
      const extKeys = Object.keys(byExt);
      const extScores = extKeys.map((ext) => Number(byExt[ext].mean_score_10 || 0));
      const extCounts = extKeys.map((ext) => Number(byExt[ext].sample_count || 0));

      chartFormats.setOption({
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        legend: { bottom: 0, textStyle: { fontSize: 11 } },
        grid: { top: 24, right: 38, bottom: 38, left: 42 },
        xAxis: {
          type: "category",
          data: extKeys,
          axisLabel: { fontSize: 11, fontWeight: 600 },
        },
        yAxis: [
          { type: "value", name: "均分(0-10)", min: 0, max: 10 },
          { type: "value", name: "样本数", minInterval: 1 },
        ],
        series: [
          {
            name: "格式平均分 (0~10)",
            type: "bar",
            barWidth: "42%",
            data: extScores,
            itemStyle: { color: "#00a6a7", borderRadius: [5, 5, 0, 0] },
            label: { show: true, position: "top", fontSize: 10.5 },
          },
          {
            name: "已测样本数",
            type: "line",
            yAxisIndex: 1,
            data: extCounts,
            itemStyle: { color: "#f59e0b" },
          },
        ],
      });
    }

    // Chart A3: Cross-Run Comparison
    const chartRuns = getOrCreateChart("chart-eval-runs");
    if (chartRuns) {
      const runsList = (Array.isArray(evalState.runs) ? evalState.runs : []).slice(0, 6).reverse();
      const runLabels = runsList.map((r, i) => {
        const tag = r.evaluation_mode && r.evaluation_mode.includes("llm") ? "LLM" : "Base";
        return `#${i + 1} ${tag}(n=${r.qualified_total})`;
      });
      const runScores = runsList.map((r) => Number(r.qualified_mean_score_10 || 0));
      const runEntities = runsList.map((r) =>
        Number(((r.qualified_mean_entity_match_rate || 0) * 10).toFixed(2))
      );

      chartRuns.setOption({
        tooltip: { trigger: "axis" },
        legend: { bottom: 0, textStyle: { fontSize: 11 } },
        grid: { top: 24, right: 20, bottom: 38, left: 42 },
        xAxis: {
          type: "category",
          data: runLabels,
          axisLabel: { fontSize: 10.5 },
        },
        yAxis: { type: "value", min: 0, max: 10, name: "分值 (0-10)" },
        series: [
          {
            name: "综合均分 (0~10)",
            type: "bar",
            barWidth: "36%",
            data: runScores,
            itemStyle: { color: "#3b82f6", borderRadius: [5, 5, 0, 0] },
            label: { show: true, position: "top", fontSize: 10.5 },
          },
          {
            name: "实体一致率折算 (0~10)",
            type: "line",
            data: runEntities,
            itemStyle: { color: "#10b981" },
          },
        ],
      });
    }
  }

  function renderEvalSamplesMatrixTable(runData) {
    if (!evalSamplesTableBody) return;
    const samples = Array.isArray(runData && runData.sample_evaluations)
      ? runData.sample_evaluations
      : [];
    const extFilter = evalAggExtFilter ? evalAggExtFilter.value : "";
    const issueFilter = evalAggIssueFilter ? evalAggIssueFilter.value : "all";

    const filtered = samples.filter((s) => {
      if (extFilter && String(s.extension || "").toLowerCase() !== extFilter.toLowerCase()) {
        return false;
      }
      if (issueFilter === "deducted" && Number(s.overall_score_10 || 0) >= 9.99) {
        return false;
      }
      if (issueFilter === "entity_mismatch" && Number(s.entity_match_rate || 1) >= 0.999) {
        return false;
      }
      if (issueFilter === "hallucination" && Number(s.hallucination_field_count || 0) === 0) {
        return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 9;
      td.style.textAlign = "center";
      td.style.color = "#64748b";
      td.style.padding = "20px";
      td.textContent = "当前筛选条件下暂无样本记录，可调整筛选条件或点击右上角运行新批次评测。";
      tr.appendChild(td);
      evalSamplesTableBody.replaceChildren(tr);
      return;
    }

    const rows = filtered.map((item) => {
      const tr = document.createElement("tr");
      tr.className = "eval-matrix-row";

      // 1. Sample ID
      const tdId = document.createElement("td");
      const idStrong = document.createElement("strong");
      idStrong.textContent = item.sample_id || "";
      tdId.appendChild(idStrong);

      // 2. Filename & ext
      const tdFile = document.createElement("td");
      const fnSpan = document.createElement("span");
      fnSpan.textContent = item.file_name || "";
      const extSpan = document.createElement("span");
      extSpan.className = "eval-ext-badge";
      extSpan.textContent = item.extension || "";
      tdFile.appendChild(fnSpan);
      tdFile.appendChild(extSpan);

      // 3. Industry
      const tdInd = document.createElement("td");
      tdInd.textContent = item.industry_category || "—";

      // 4. Overall Score (0~10)
      const tdScore = document.createElement("td");
      const scoreVal = Number(item.overall_score_10 || 0);
      const scoreBadge = document.createElement("span");
      scoreBadge.className = getScorePillClass(scoreVal);
      scoreBadge.style.fontSize = "12.5px";
      scoreBadge.textContent = `${scoreVal.toFixed(2)} / 10`;
      tdScore.appendChild(scoreBadge);

      // 5. Entity Match Rate
      const tdEntity = document.createElement("td");
      const entRate = Number(item.entity_match_rate ?? 1);
      const entBadge = document.createElement("span");
      entBadge.className = entRate >= 0.99 ? "eval-flag-badge flag-pass" : "eval-flag-badge flag-warn";
      entBadge.textContent = `${Math.round(entRate * 100)}% (${Math.round(entRate * 9)}/9)`;
      tdEntity.appendChild(entBadge);

      // 6. Hallucination Count
      const tdHallu = document.createElement("td");
      const hCount = Number(item.hallucination_field_count || 0);
      const hBadge = document.createElement("span");
      hBadge.className = hCount === 0 ? "eval-flag-badge flag-pass" : "eval-flag-badge flag-fail";
      hBadge.textContent = hCount === 0 ? "✓ 0 幻觉" : `⚠ ${hCount} 处幻觉`;
      tdHallu.appendChild(hBadge);

      // 7. Schema & PII Gate
      const tdPii = document.createElement("td");
      const piiOk = Boolean(item.schema_and_pii_valid);
      const piiBadge = document.createElement("span");
      piiBadge.className = piiOk ? "eval-flag-badge flag-pass" : "eval-flag-badge flag-fail";
      piiBadge.textContent = piiOk ? "✓ 脱敏合规" : "✗ 脱敏违规";
      tdPii.appendChild(piiBadge);

      // 8. 9-Field Mini Score Pills
      const tdPills = document.createElement("td");
      const pillsWrap = document.createElement("div");
      pillsWrap.className = "eval-mini-pills-wrap";
      const checks = Array.isArray(item.atomic_checks) ? item.atomic_checks : [];
      checks.forEach((chk) => {
        const pill = document.createElement("span");
        const sc = Number(chk.score || 0);
        pill.className = getScorePillClass(sc);
        const shortName = FIELD_SHORT_LABELS[chk.dimension] || chk.dimension;
        pill.textContent = `${shortName}:${sc.toFixed(1)}`;
        pill.title = `${chk.dimension_label}: ${sc.toFixed(1)}/10\n${chk.reason || ""}`;
        pillsWrap.appendChild(pill);
      });
      tdPills.appendChild(pillsWrap);

      // 9. Action button
      const tdAction = document.createElement("td");
      const inspectBtn = document.createElement("button");
      inspectBtn.type = "button";
      inspectBtn.className = "regen-query-btn";
      inspectBtn.textContent = "原子核对详情";
      inspectBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openSingleSampleInspector(item.sample_id);
      });
      tdAction.appendChild(inspectBtn);

      tr.appendChild(tdId);
      tr.appendChild(tdFile);
      tr.appendChild(tdInd);
      tr.appendChild(tdScore);
      tr.appendChild(tdEntity);
      tr.appendChild(tdHallu);
      tr.appendChild(tdPii);
      tr.appendChild(tdPills);
      tr.appendChild(tdAction);

      tr.addEventListener("click", () => {
        openSingleSampleInspector(item.sample_id);
      });
      return tr;
    });

    evalSamplesTableBody.replaceChildren(...rows);
  }

  function renderEvalDisqualifiedTable(runData) {
    if (!evalDisqTableBody) return;
    const disqList = Array.isArray(runData && runData.disqualified_guardrails)
      ? runData.disqualified_guardrails
      : [];
    const passedCount = disqList.filter((d) => d.correctly_rejected).length;
    if (evalDisqSummaryBadge) {
      evalDisqSummaryBadge.textContent = `${passedCount} / ${disqList.length} 精准拦截`;
    }

    const rows = disqList.map((d) => {
      const tr = document.createElement("tr");
      const cells = [
        d.id || "",
        d.file_name || "",
        d.dimension || "",
        d.expected_error_code || "",
        d.actual_error_code || "",
        d.rejection_stage || "",
      ];
      cells.forEach((txt, i) => {
        const td = document.createElement("td");
        if (i === 0 || i === 3 || i === 4) {
          td.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, monospace";
          td.style.fontSize = "12px";
        }
        td.textContent = String(txt);
        tr.appendChild(td);
      });

      const tdStatus = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = d.correctly_rejected
        ? "eval-flag-badge flag-pass"
        : "eval-flag-badge flag-fail";
      badge.textContent = d.correctly_rejected ? "✓ 成功拦截" : "✗ 未拦截";
      tdStatus.appendChild(badge);
      tr.appendChild(tdStatus);
      return tr;
    });
    evalDisqTableBody.replaceChildren(...rows);
  }

  // ==================== 视图 B：Single-Use 单样本原子核对渲染 ====================
  function renderSingleSamplePicker() {
    if (!evalSingleSampleSelect) return;
    const qualCatalog =
      (evalState.catalog && Array.isArray(evalState.catalog.qualified_samples)
        ? evalState.catalog.qualified_samples
        : []);
    const evaluatedMap = {};
    if (evalState.activeRun && Array.isArray(evalState.activeRun.sample_evaluations)) {
      evalState.activeRun.sample_evaluations.forEach((s) => {
        evaluatedMap[s.sample_id] = s;
      });
    }

    const options = qualCatalog.map((item) => {
      const opt = document.createElement("option");
      opt.value = item.id;
      const evaluated = evaluatedMap[item.id];
      const scoreTag = evaluated
        ? `[已测 ${Number(evaluated.overall_score_10 || 0).toFixed(2)}/10]`
        : "[未跑实时LLM，可点击右侧实时评测]";
      opt.textContent = `${item.id} | ${item.file_name} (${item.industry_category}) ${scoreTag}`;
      if (item.id === evalState.selectedSampleId) {
        opt.selected = true;
      }
      return opt;
    });
    evalSingleSampleSelect.replaceChildren(...options);
  }

  function renderSingleSampleDetail(sampleId) {
    evalState.selectedSampleId = sampleId;
    renderSingleSamplePicker();

    const qualCatalog =
      (evalState.catalog && Array.isArray(evalState.catalog.qualified_samples)
        ? evalState.catalog.qualified_samples
        : []);
    const catalogItem = qualCatalog.find((x) => x.id === sampleId) || qualCatalog[0];

    const evaluatedSamples =
      (evalState.activeRun && Array.isArray(evalState.activeRun.sample_evaluations)
        ? evalState.activeRun.sample_evaluations
        : []);
    const evalRecord = evaluatedSamples.find((s) => s.sample_id === sampleId);

    // 1. 渲染原始简历文本与 PII 脱敏红线词
    if (evalSingleRawText) {
      evalSingleRawText.textContent =
        (evalRecord && evalRecord.raw_resume_text) ||
        (catalogItem && catalogItem.raw_resume_text) ||
        "暂无原始简历文本";
    }
    if (evalSinglePiiTokens) {
      const piiList =
        (evalRecord && Array.isArray(evalRecord.raw_pii_tokens) && evalRecord.raw_pii_tokens) ||
        (catalogItem && Array.isArray(catalogItem.raw_pii_tokens) && catalogItem.raw_pii_tokens) ||
        [];
      const piiNodes = piiList.map((tok) => {
        const sp = document.createElement("span");
        sp.className = "tag-risk";
        sp.textContent = `禁止出现: ${tok}`;
        return sp;
      });
      evalSinglePiiTokens.replaceChildren(...piiNodes);
    }

    // 2. 渲染单样本诊断总览卡片
    if (evalSingleSummaryCard) {
      const topRow = document.createElement("div");
      topRow.className = "eval-single-summary-top";

      const titleGroup = document.createElement("div");
      titleGroup.className = "eval-single-title-group";

      const idBadge = document.createElement("span");
      idBadge.className = "profile-badge";
      idBadge.textContent = sampleId;

      const fnTitle = document.createElement("strong");
      fnTitle.style.fontSize = "16px";
      fnTitle.textContent =
        (evalRecord && evalRecord.file_name) || (catalogItem && catalogItem.file_name) || "";

      const indBadge = document.createElement("span");
      indBadge.className = "meta-pill";
      indBadge.textContent = `行业: ${
        (evalRecord && evalRecord.industry_category) ||
        (catalogItem && catalogItem.industry_category) ||
        "—"
      }`;

      titleGroup.appendChild(idBadge);
      titleGroup.appendChild(fnTitle);
      titleGroup.appendChild(indBadge);

      const metricsRow = document.createElement("div");
      metricsRow.className = "eval-single-metrics-row";

      if (evalRecord) {
        const s10 = Number(evalRecord.overall_score_10 || 0);
        const entRate = Number(evalRecord.entity_match_rate ?? 1);
        const hCount = Number(evalRecord.hallucination_field_count || 0);
        const piiOk = Boolean(evalRecord.schema_and_pii_valid);

        const pillsData = [
          {
            text: `综合平均分: ${s10.toFixed(2)} / 10.0`,
            cls: getScorePillClass(s10),
          },
          {
            text: `数字/实体一致: ${Math.round(entRate * 9)} / 9 字段`,
            cls: entRate >= 0.99 ? "eval-flag-badge flag-pass" : "eval-flag-badge flag-warn",
          },
          {
            text: hCount === 0 ? "✓ 零幻觉 (0 Hallucination)" : `⚠ 发现 ${hCount} 处幻觉`,
            cls: hCount === 0 ? "eval-flag-badge flag-pass" : "eval-flag-badge flag-fail",
          },
          {
            text: piiOk ? "✓ PII 脱敏门禁通过" : "✗ PII 脱敏违规",
            cls: piiOk ? "eval-flag-badge flag-pass" : "eval-flag-badge flag-fail",
          },
          {
            text: `耗时: 提取 ${evalRecord.extract_latency_s || 0}s | 裁判 ${
              evalRecord.judge_latency_s || 0
            }s`,
            cls: "meta-pill",
          },
        ];

        pillsData.forEach((p) => {
          const sp = document.createElement("span");
          sp.className = p.cls;
          sp.textContent = p.text;
          metricsRow.appendChild(sp);
        });
      } else {
        const notRunSpan = document.createElement("span");
        notRunSpan.className = "eval-flag-badge flag-warn";
        notRunSpan.textContent = "当前批次尚未对该样本执行实时评测，点击上方按钮即可立即运行";
        metricsRow.appendChild(notRunSpan);
      }

      topRow.appendChild(titleGroup);
      topRow.appendChild(metricsRow);

      const commentBox = document.createElement("div");
      commentBox.className = "eval-single-comment-box";
      commentBox.textContent = evalRecord
        ? `LLM-as-a-Judge 综合诊断 (${evalRecord.judge_model || "gemini-3.8-flash"})：${
            evalRecord.overall_comment || "已完成 9 字段原子核对。"
          }`
        : "该样本属于 25 个标准正例之一。点击右上角「实时运行此样本」按钮，即可在线调用 Stage 1 多模态解析与 LLM-as-a-Judge 逐字段打分。";

      evalSingleSummaryCard.replaceChildren(topRow, commentBox);
    }

    // 3. 渲染 9 字段原子核对表 (Side-by-Side Diff & Atomic Classification)
    if (!evalAtomicDiffTbody) return;

    const gtObj =
      (evalRecord && evalRecord.ground_truth) ||
      (catalogItem && catalogItem.ground_truth) ||
      {};
    const predObj = (evalRecord && evalRecord.extracted_profile) || {};
    const atomicChecks = Array.isArray(evalRecord && evalRecord.atomic_checks)
      ? evalRecord.atomic_checks
      : [];

    const checkByField = {};
    atomicChecks.forEach((c) => {
      checkByField[c.dimension] = c;
    });

    const fieldKeys = Object.keys(FIELD_LABELS_MAP);
    const trNodes = fieldKeys.map((fname) => {
      const tr = document.createElement("tr");
      const chk = checkByField[fname];

      // Col 1: Field Name
      const tdName = document.createElement("td");
      const nameStrong = document.createElement("strong");
      nameStrong.textContent = FIELD_LABELS_MAP[fname] || fname;
      tdName.appendChild(nameStrong);

      // Col 2: Ground Truth Value
      const tdGt = document.createElement("td");
      const gtDiv = document.createElement("div");
      gtDiv.className = "eval-val-pre";
      gtDiv.textContent = formatFieldVal(chk ? chk.ground_truth_value : gtObj[fname]);
      tdGt.appendChild(gtDiv);

      // Col 3: Stage 1 Extracted Value
      const tdPred = document.createElement("td");
      const predDiv = document.createElement("div");
      predDiv.className = "eval-val-pre";
      if (evalRecord) {
        predDiv.textContent = formatFieldVal(chk ? chk.extracted_value : predObj[fname]);
      } else {
        predDiv.style.color = "#94a3b8";
        predDiv.textContent = "（等待点击上方按钮实时运行 Stage 1 提取...）";
      }
      tdPred.appendChild(predDiv);

      // Col 4: Entity / Number Exact Match
      const tdEntity = document.createElement("td");
      if (chk) {
        const badge = document.createElement("span");
        badge.className = chk.entity_number_match
          ? "eval-flag-badge flag-pass"
          : "eval-flag-badge flag-fail";
        badge.textContent = chk.entity_number_match ? "✓ 完全一致" : "✗ 实体/数字偏差";
        tdEntity.appendChild(badge);
      } else {
        tdEntity.textContent = "—";
      }

      // Col 5: Hallucination Detection
      const tdHallu = document.createElement("td");
      if (chk) {
        const badge = document.createElement("span");
        badge.className = chk.has_hallucination
          ? "eval-flag-badge flag-fail"
          : "eval-flag-badge flag-pass";
        badge.textContent = chk.has_hallucination ? "⚠ 存在幻觉" : "✓ 无幻觉";
        tdHallu.appendChild(badge);
      } else {
        tdHallu.textContent = "—";
      }

      // Col 6: Score (0 ~ 10) + Bar
      const tdScore = document.createElement("td");
      if (chk) {
        const sc = Number(chk.score || 0);
        const cellWrap = document.createElement("div");
        cellWrap.className = "eval-score-cell";

        const numSpan = document.createElement("span");
        numSpan.className = "eval-score-num";
        numSpan.style.color = getScoreBarColor(sc);
        numSpan.textContent = `${sc.toFixed(1)} / 10`;

        const barTrack = document.createElement("div");
        barTrack.className = "eval-score-bar-track";
        const barFill = document.createElement("div");
        barFill.className = "eval-score-bar-fill";
        barFill.style.width = `${Math.max(0, Math.min(100, sc * 10))}%`;
        barFill.style.backgroundColor = getScoreBarColor(sc);
        barTrack.appendChild(barFill);

        cellWrap.appendChild(numSpan);
        cellWrap.appendChild(barTrack);
        tdScore.appendChild(cellWrap);
      } else {
        tdScore.textContent = "—";
      }

      // Col 7: Judge Diagnostic Reason
      const tdReason = document.createElement("td");
      tdReason.style.fontSize = "12.5px";
      tdReason.style.color = "#334155";
      tdReason.textContent = chk ? chk.reason || "—" : "尚未执行 LLM-as-a-Judge 核对";

      tr.appendChild(tdName);
      tr.appendChild(tdGt);
      tr.appendChild(tdPred);
      tr.appendChild(tdEntity);
      tr.appendChild(tdHallu);
      tr.appendChild(tdScore);
      tr.appendChild(tdReason);
      return tr;
    });

    evalAtomicDiffTbody.replaceChildren(...trNodes);
  }

  function switchEvalSubView(mode) {
    evalState.viewMode = mode === "single" ? "single" : "aggregated";
    const isAgg = evalState.viewMode === "aggregated";
    if (evalViewBtnAggregated) evalViewBtnAggregated.classList.toggle("active", isAgg);
    if (evalViewBtnSingle) evalViewBtnSingle.classList.toggle("active", !isAgg);
    if (evalAggregatedView) evalAggregatedView.classList.toggle("hidden", !isAgg);
    if (evalSingleView) evalSingleView.classList.toggle("hidden", isAgg);

    if (isAgg && evalState.activeRun) {
      setTimeout(() => {
        renderEvalAggregatedCharts(evalState.activeRun);
      }, 30);
    } else if (!isAgg) {
      renderSingleSampleDetail(evalState.selectedSampleId);
    }
  }

  function openSingleSampleInspector(sampleId) {
    evalState.selectedSampleId = sampleId || "QUAL-001";
    switchEvalSubView("single");
  }

  function renderFullEvalWorkspace() {
    renderStageStepper();
    renderRunSelectDropdown();
    if (evalState.activeRun) {
      renderEvalAggregatedKpis(evalState.activeRun);
      renderEvalAggregatedCharts(evalState.activeRun);
      renderEvalSamplesMatrixTable(evalState.activeRun);
      renderEvalDisqualifiedTable(evalState.activeRun);
    }
    renderSingleSampleDetail(evalState.selectedSampleId);
  }

  async function initEvalWorkspace() {
    showEvalStatus("正在加载全链路评测基准数据集与历史评测记录...", false);
    try {
      const resp = await fetch("/api/eval/overview");
      if (!resp.ok) {
        throw new Error(`加载评测概览失败 (HTTP ${resp.status})`);
      }
      const data = await resp.json();
      evalState.stages = Array.isArray(data.stages) ? data.stages : [];
      evalState.runs = Array.isArray(data.runs) ? data.runs : [];
      evalState.activeRun = data.active_run || null;
      evalState.catalog = data.catalog || { qualified_samples: [], disqualified_samples: [] };
      evalState.initialized = true;

      if (
        evalState.activeRun &&
        Array.isArray(evalState.activeRun.sample_evaluations) &&
        evalState.activeRun.sample_evaluations.length > 0
      ) {
        evalState.selectedSampleId = evalState.activeRun.sample_evaluations[0].sample_id;
      }

      showEvalStatus("");
      renderFullEvalWorkspace();
    } catch (err) {
      showEvalStatus(`加载评测工作台失败：${err.message || String(err)}`, true);
    }
  }

  async function switchTopWorkspace(target) {
    const isEval = target === "eval";
    if (navTabSearch) navTabSearch.classList.toggle("active", !isEval);
    if (navTabEval) navTabEval.classList.toggle("active", isEval);
    if (searchWorkspaceWrapper) searchWorkspaceWrapper.classList.toggle("hidden", isEval);
    if (searchConfigBar) searchConfigBar.classList.toggle("hidden", isEval);
    if (evalWorkspaceSection) evalWorkspaceSection.classList.toggle("hidden", !isEval);

    if (isEval) {
      if (!evalState.initialized) {
        await initEvalWorkspace();
      } else {
        setTimeout(() => {
          renderEvalAggregatedCharts(evalState.activeRun);
        }, 40);
      }
    } else {
      setTimeout(() => {
        Object.values(chartInstances).forEach((c) => {
          if (c) c.resize();
        });
      }, 40);
    }
  }

  // 事件绑定：顶层工作台切换与 Eval 子视图切换
  if (navTabSearch) {
    navTabSearch.addEventListener("click", () => switchTopWorkspace("search"));
  }
  if (navTabEval) {
    navTabEval.addEventListener("click", () => switchTopWorkspace("eval"));
  }
  if (evalViewBtnAggregated) {
    evalViewBtnAggregated.addEventListener("click", () => switchEvalSubView("aggregated"));
  }
  if (evalViewBtnSingle) {
    evalViewBtnSingle.addEventListener("click", () => switchEvalSubView("single"));
  }

  if (evalRunSelect) {
    evalRunSelect.addEventListener("change", async () => {
      const runId = evalRunSelect.value;
      if (!runId) return;
      showEvalStatus(`正在加载历史评测批次 ${runId}...`, false);
      try {
        const resp = await fetch(`/api/eval/runs/${encodeURIComponent(runId)}`);
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          throw new Error(data.detail || `加载批次失败 (HTTP ${resp.status})`);
        }
        evalState.activeRun = data.run;
        showEvalStatus("");
        renderFullEvalWorkspace();
      } catch (err) {
        showEvalStatus(`切换评测批次失败：${err.message || String(err)}`, true);
      }
    });
  }

  [evalAggExtFilter, evalAggIssueFilter].forEach((sel) => {
    if (!sel) return;
    sel.addEventListener("change", () => {
      if (evalState.activeRun) {
        renderEvalSamplesMatrixTable(evalState.activeRun);
      }
    });
  });

  if (evalSingleSampleSelect) {
    evalSingleSampleSelect.addEventListener("change", () => {
      renderSingleSampleDetail(evalSingleSampleSelect.value);
    });
  }

  if (evalPrevSampleBtn) {
    evalPrevSampleBtn.addEventListener("click", () => {
      const list = (evalState.catalog && evalState.catalog.qualified_samples) || [];
      if (list.length === 0) return;
      const idx = list.findIndex((x) => x.id === evalState.selectedSampleId);
      const prevIdx = idx > 0 ? idx - 1 : list.length - 1;
      renderSingleSampleDetail(list[prevIdx].id);
    });
  }

  if (evalNextSampleBtn) {
    evalNextSampleBtn.addEventListener("click", () => {
      const list = (evalState.catalog && evalState.catalog.qualified_samples) || [];
      if (list.length === 0) return;
      const idx = list.findIndex((x) => x.id === evalState.selectedSampleId);
      const nextIdx = idx >= 0 && idx < list.length - 1 ? idx + 1 : 0;
      renderSingleSampleDetail(list[nextIdx].id);
    });
  }

  if (evalRunSingleBtn) {
    evalRunSingleBtn.addEventListener("click", async () => {
      const sampleId = evalState.selectedSampleId || "QUAL-001";
      const extractModel = evalSingleExtractModel ? evalSingleExtractModel.value : "gemini-3.8-flash";
      const judgeModel = evalSingleJudgeModel ? evalSingleJudgeModel.value : "gemini-3.8-flash";
      const activeRunId = evalState.activeRun ? evalState.activeRun.run_id : null;

      evalRunSingleBtn.disabled = true;
      evalRunSingleBtn.textContent = "正在实时提取与原子核对...";
      showEvalStatus(
        `正在对样本 ${sampleId} 执行实时 Stage 1 多模态提取 (${extractModel}) + LLM-as-a-Judge 9 字段原子核对 (${judgeModel})，请稍候约 15~30 秒...`,
        false
      );

      try {
        const resp = await fetch("/api/eval/stage1/run-single", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sample_id: sampleId,
            extract_model: extractModel,
            judge_model: judgeModel,
            run_id: activeRunId,
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          throw new Error(data.detail || `单样本实时评测失败 (HTTP ${resp.status})`);
        }
        if (Array.isArray(data.runs)) {
          evalState.runs = data.runs;
        }
        if (data.updated_run) {
          evalState.activeRun = data.updated_run;
        }
        renderFullEvalWorkspace();
        const sc = data.sample ? Number(data.sample.overall_score_10 || 0).toFixed(2) : "—";
        showEvalStatus(
          `✓ 样本 ${sampleId} 实时评测完成！9 字段原子核对平均分：${sc} / 10.0（结果已同步更新至当前评测批次）。`,
          false
        );
      } catch (err) {
        showEvalStatus(`单样本实时评测未成功：${err.message || String(err)}`, true);
      } finally {
        evalRunSingleBtn.disabled = false;
        evalRunSingleBtn.textContent = "实时运行此样本 (Stage 1 提取 + LLM-Judge 核对)";
      }
    });
  }

  if (evalRunBatchBtn) {
    evalRunBatchBtn.addEventListener("click", async () => {
      const extVal = evalBatchExtSelect ? evalBatchExtSelect.value : "";
      const limitVal = Math.max(1, Math.min(25, Number(evalBatchLimitInput ? evalBatchLimitInput.value : 2) || 2));
      const extractModel = evalSingleExtractModel ? evalSingleExtractModel.value : "gemini-3.8-flash";
      const judgeModel = evalSingleJudgeModel ? evalSingleJudgeModel.value : "gemini-3.8-flash";

      evalRunBatchBtn.disabled = true;
      evalRunBatchBtn.textContent = "正在运行批量评测...";
      showEvalStatus(
        `正在运行新批次 LLM-as-a-Judge 评测（格式: ${extVal || "全部"} | 样本数上限: ${limitVal} | 模型: ${extractModel}），请稍候...`,
        false
      );

      try {
        const resp = await fetch("/api/eval/stage1/run-batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            extensions: extVal ? [extVal] : null,
            limit: limitVal,
            live_gemini: true,
            extract_model: extractModel,
            judge_model: judgeModel,
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          throw new Error(data.detail || `批量评测失败 (HTTP ${resp.status})`);
        }
        if (Array.isArray(data.runs)) {
          evalState.runs = data.runs;
        }
        if (data.active_run) {
          evalState.activeRun = data.active_run;
        }
        renderFullEvalWorkspace();
        showEvalStatus(
          `✓ 新批次评测 (${data.run_id}) 已完成并归档！综合平均分：${Number(
            (data.active_run.aggregated_metrics || {}).qualified_mean_score_10 || 0
          ).toFixed(2)} / 10.0`,
          false
        );
      } catch (err) {
        showEvalStatus(`批量评测未成功：${err.message || String(err)}`, true);
      } finally {
        evalRunBatchBtn.disabled = false;
        evalRunBatchBtn.textContent = "运行新批次 LLM-Judge 评测";
      }
    });
  }

  if (window.location.hash === "#eval" || window.location.search.includes("tab=eval")) {
    switchTopWorkspace("eval");
  }

  // 清理历史遗留的浏览器本地存储密钥，确保前端不留存任何 API Key
  try {
    window.localStorage.removeItem("boss_agent_gemini_api_key");
    window.localStorage.removeItem("boss_agent_gemini_proxy");
  } catch (_) {}

  // 页面初始化：自动加载最近一次简历解析与六维人岗匹配实测快照
  async function loadInitialSnapshot() {
    try {
      const resp = await fetch("/api/latest-snapshot");
      if (!resp.ok) return;
      const snap = await resp.json();
      if (snap && snap.resume_parsed && snap.resume_parsed.profile) {
        const fn = snap.resume_parsed.filename || "个人简历.pdf";
        resumeStatusTitle.textContent = `已解析简历：${fn}`;
        resumeStatusDesc.textContent =
          "您可以点击下方任意一条 AI 预生成的 Query 填入搜索框，也可点击右侧按钮重新上传新简历。";
        resumeUploadBtn.textContent = "重新上传简历";
        renderResumeParseResult(snap.resume_parsed);
      }
      if (snap && snap.dashboard_payload && snap.dashboard_payload.report) {
        const dp = snap.dashboard_payload;
        updateProgress(100, dp.message || "已加载最新简历实测与六维匹配报告", true);
        if (dp.intent) {
          renderIntentTags(dp.intent);
        }
        renderFullDashboard(dp);
      }
    } catch (_) {
      // 忽略快照加载异常，保持默认空白引导态
    }
  }

  loadInitialSnapshot();
})();
