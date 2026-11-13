# BOSS直聘 URL 查询参数与岗位数据字段参考字典

本文档记录从 BOSS直聘 官方配置接口（`/wapi/zpgeek/pc/all/filter/conditions.json`）、列表接口（`/wapi/zpgeek/search/joblist.json`）及详情接口（`/wapi/zpgeek/job/detail.json`）提取的完整参数与字段规范。

---

## 一、 URL 支持的筛选维度（Query Features & 编码字典）

基础搜索 URL 格式：
`https://www.zhipin.com/web/geek/jobs?query=关键词&city=城市码&salary=薪资码&...`

*(注：除 `salary` 为单选外，`experience`、`degree`、`scale`、`stage` 等均支持用英文逗号 `,` 拼接多选，如 `degree=202,203`)*

| URL 参数名 | 筛选维度 | 官方可选值与编码（Code） |
| :--- | :--- | :--- |
| **`query`** | 搜索关键词 | 任意文本（如 `店面督导`） |
| **`city`** | 城市编码 | `100010000` 全国、`101010100` 北京、`101020100` 上海、`101280100` 广州、`101280600` 深圳、`101210100` 杭州、`101270100` 成都、`101200100` 武汉、`101190100` 南京 |
| **`multiBusinessDistrict`** | 行政区 / 商圈 | 城市下属区编码（可通过 `/wapi/zpgeek/businessDistrict.json?cityCode=...` 获取，支持逗号多选） |
| **`multiSubway`** | 地铁沿线 | 城市地铁线/站点编码 |
| **`salary`** | **薪资范围** | `402`: 3K以下 \| `403`: 3-5K \| `404`: 5-10K \| **`405`: 10-20K** \| `406`: 20-50K \| `407`: 50K以上 |
| **`experience`** | **工作经验** | `108`: 在校生 \| `102`: 应届生 \| `101`: 经验不限 \| `103`: 1年以内 \| `104`: 1-3年 \| `105`: 3-5年 \| `106`: 5-10年 \| `107`: 10年以上 |
| **`degree`** | **学历要求** | `209`: 初中及以下 \| `208`: 中专/中技 \| `206`: 高中 \| `202`: 大专 \| `203`: 本科 \| `204`: 硕士 \| `205`: 博士 |
| **`scale`** | **公司规模** | `301`: 0-20人 \| `302`: 20-99人 \| `303`: 100-499人 \| `304`: 500-999人 \| `305`: 1000-9999人 \| `306`: 10000人以上 |
| **`stage`** | **融资阶段** | `801`: 未融资 \| `802`: 天使轮 \| `803`: A轮 \| `804`: B轮 \| `805`: C轮 \| `806`: D轮及以上 \| `807`: 已上市 \| `808`: 不需要融资 |
| **`jobType`** | **求职类型** | `1901`: 全职 \| `1903`: 兼职 |
| **`payType`** | **结算方式** | `2501`: 日结 \| `2502`: 周结 \| `2503`: 月结 \| `2504`: 完工结 |
| **`partTime`** | **兼职时段** | `2701`: 周末/节假日 \| `2702`: 寒暑假 \| `2703`: 短期兼职 \| `2704`: 长期兼职 \| `2705`: 工作日 \| `2706`: 夜班 |
| **`industry`** | **公司行业** | 6位行业码（如 `100503` 批发/零售、`100020` 互联网等） |
| **`position`** | **标准职位类别** | 6位职位树编码（如 `290302` 导购） |

---

## 二、 每条招聘信息包含的数据标签（Labels / Fields）

### 第 1 层：列表接口 (`/wapi/zpgeek/search/joblist.json`) 原生字段

1. **岗位基础标签**
   * `jobName`：岗位名称
   * `salaryDesc`：薪资范围（如 `"14-24K"`、`"15-25K·14薪"`）
   * `jobExperience` / `jobDegree` / `jobLabels`：经验要求、学历要求、综合标签数组
   * `skills`：核心技能/要求标签数组
   * `daysPerWeekDesc` / `leastMonthDesc`：每周工作天数、最少实习/兼职月数
   * `encryptJobId` / `securityId` / `lid`：岗位唯一加密 ID 与追踪参数（用于请求详情接口）
2. **地理位置与精确坐标**
   * `cityName` / `areaDistrict` / `businessDistrict`：城市 · 行政区 · 商圈
   * `gps.longitude` & `gps.latitude`：高德经纬度坐标
   * `outland`：是否异地派遣/外派岗位（`0/1`）
3. **公司与福利标签**
   * `brandName` / `encryptBrandId` / `brandLogo`：公司简称、公司加密 ID、Logo
   * `brandIndustry` & `industry`：所属行业名称及行业代码
   * `brandStageName` / `brandScaleName`：融资阶段、公司人数规模
   * `welfareList`：福利待遇标签数组（如 `["五险一金", "底薪加提成", "带薪年假", "周末双休"]`）
4. **HR 状态与渠道属性**
   * `bossName` / `bossTitle`：招聘人姓名与职务
   * `bossOnline`：HR 当前是否实时在线（`true` / `false`）
   * `goldHunter`：是否为猎头岗位（`0` 直招 / `1` 猎头）
   * `proxyJob` / `proxyType`：是否为代招/劳务派遣岗位
   * `anonymous`：是否匿名发布

---

### 第 2 层：详情接口 (`/wapi/zpgeek/job/detail.json`) 深度字段

请求参数：`?securityId=<job.securityId>&lid=<job.lid>`

1. **`jobInfo.postDescription`**：完整的岗位职责与任职要求正文（JD 全文）。
2. **`jobInfo.address`**：精确到商场/写字楼门牌号的办公地址。
3. **`bossInfo.activeTimeDesc`**：HR 活跃度标签（如 `"刚刚活跃"`、`"今日活跃"`、`"本周活跃"`、`"半年前活跃"`）。
4. **`jobInfo.positionName`**：BOSS直聘内部归类的标准三级岗位名。
5. **`brandComInfo.introduce`**：公司简介全文。
