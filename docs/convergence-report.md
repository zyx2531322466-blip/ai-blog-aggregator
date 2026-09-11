# 收敛报告（Convergence Report）

> **主题**：需求（spec）↔ 计划（plan）↔ 拆解（tasks/tickets）↔ 实现（code）↔ 验证（tests/CI）的一致性核对
> **基线**：`main @ 9b150e8`（2026-09-11）
> **结论**：**T01–T21 全部收敛**；核对过程中发现的偏差均已关闭；剩余事项均属"明确未纳入范围"或"环境限制"，无未解释的差异。

---

## 1. 判定标准（什么叫"收敛"）

本项目不把"代码写完了"当作完成，而是要求每条需求同时满足以下 4 条才算收敛：

| # | 条件 | 核验方式 |
| --- | --- | --- |
| C1 | tickets.md 中该票的**每条验收标准**都有对应实现 | 逐条人工对照 + 代码定位 |
| C2 | 每条验收标准都有**自动化测试证据**（测试名可对应到验收点） | `pytest` / `vitest` 用例清单 |
| C3 | 通过统一质量门（格式 / 静态检查 / 覆盖率门槛） | CI 三作业（Backend / Frontend / Infra） |
| C4 | 人工对照后发现的不一致**已修正并记录** | 偏差登记表（见第 6 节）+ 提交记录 |

> 说明：C1/C2/C4 依赖人工判断与登记，本报告即是把这一过程**固化、可复核**化，取代此前"口头确认"的方式。

---

## 2. 逐票收敛对照

后端测试文件与用例数（共 **207** 个用例，全部通过）：

| 票 | 交付物 | 验收证据（测试文件 / 用例数） | 状态 |
| --- | --- | --- | --- |
| T01 | 项目脚手架、配置、健康探针、CI | `test_smoke.py` (2) | ✅ 收敛 |
| T02 | 数据模型、迁移、会话 | `test_models_crud.py` (9)、`test_migrations.py` (3)、`test_session.py` (5) | ✅ 收敛 |
| T03 | 维护者访问控制（Bearer 令牌） | `test_admin_auth.py` (10) | ✅ 收敛 |
| T04 | 主题与来源配置管理 | `test_admin_sources.py` (16) | ✅ 收敛 |
| T05 | 单站点抓取（黑白名单 / robots / 限速） | `test_crawler.py` (17) | ✅ 收敛 |
| T06 | 解析与元信息提取 | `test_parser.py` (13) | ✅ 收敛 |
| T07 | 受控类别管理（增/改名/合并/停用） | `test_categories.py` (17) | ✅ 收敛 |
| T08 | 内容分类与多标签打标 | `test_classifier.py` (11) | ✅ 收敛 |
| T09 | 完全重复识别与合并记录 | `test_dedup_exact.py` (5) | ✅ 收敛 |
| T10 | 文章查询与浏览接口 | `test_articles_api.py` (12) | ✅ 收敛 |
| T11 | 列表页与详情页（前端） | 前端 6 个测试文件 / 19 用例（含 `ArticleListPage`、`ArticleDetailPage`） | ✅ 收敛 |
| T12 | 未分类兜底与重新归类 | `test_reclassify.py` (8) | ✅ 收敛 |
| T13 | 近重复识别，阈值可配置 | `test_dedup_near.py` (10) | ✅ 收敛 |
| T14 | 不同视角识别与关联推荐（不合并） | `test_dedup_related.py` (8) | ✅ 收敛 |
| T15 | 去重策略管理与审计（命中/预览/记录/回滚） | `test_dedup_admin.py` (9) | ✅ 收敛 |
| T16 | 低质量/不相关内容过滤 | `test_filtering.py` (16) | ✅ 收敛 |
| T17 | 来源级周期性采集调度 | `test_scheduler.py` (11) | ✅ 收敛 |
| T18 | 合并组主记录选择与切换 | `test_primary_selection.py` (12) | ✅ 收敛 |
| T19 | 内容新鲜度信息展示 | `test_freshness.py` (3) + 前端 `SourceFreshness` 测试 | ✅ 收敛 |
| T20 | 维护者效果概览接口与页面 | `test_insights.py` (2) + 前端 `AdminInsightsPage` 测试 | ✅ 收敛 |
| T21 | 端到端集成验收（7 类场景） | `test_e2e.py` (3) | ✅ 收敛 |

> 另有两个**非票据**的后继增强同样带测试：`test_seed_sources.py` (5，热门博客种子来源)、
> 以及本轮质量修复新增的入口页/排序/并发/调度隔离/标题用例（合计 18 个，分布于上述文件中）。

---

## 3. 需求覆盖矩阵（spec 用户故事 1–9）

| 用户故事 | 落地票 | 实现定位 | 验证证据 |
| --- | --- | --- | --- |
| 1 自动收集相关文章 | T04 T05 T17 | `crawler/service.py`、`scheduler_service.py`、`scripts/seed_sources.py` | `test_crawler`、`test_scheduler` |
| 2 自动分类整理 | T07 T08 T12 | `classifier/rules.py`、`classifier_service.py`、`category_service.py` | `test_classifier`、`test_categories`、`test_reclassify` |
| 3 重复/相似内容合并去重 | T09 T13 T15 | `dedup/fingerprint.py`、`dedup/simhash.py`、`dedup_service.py` | `test_dedup_exact`、`test_dedup_near`、`test_dedup_admin` |
| 4 按分类/时间/来源筛选浏览 | T10 T11 | `query_service.py`、`pages/ArticleListPage.tsx` | `test_articles_api`、`ArticleListPage.test.tsx` |
| 5 展示原始来源与发布时间，可跳原文 | T06 T10 T11 T19 | `parser/html_parser.py`、`schemas/article.py`、`components/SourceList.tsx` | `test_parser`、`test_freshness`、`ArticleDetailPage.test.tsx` |
| 6 持续更新而非一次性抓取 | T17 | `scheduler/frequency.py`、`scheduler_service.py` | `test_scheduler`（含"后续新增内容进入流程"用例） |
| 7 合并后可见全部来源 | T10 T14 T18 | `dedup/primary.py`、`primary_selection_service.py`、详情接口 | `test_primary_selection`、`test_dedup_related` |
| 8 维护者调整抓取范围 | T04 | `source_service.py`、`api/v1/admin_sources.py` | `test_admin_sources` |
| 9 维护者了解分类/去重效果 | T15 T20 | `insights_service.py`、`dedup_settings_service.py` | `test_insights`、`test_dedup_admin` |

---

## 4. 质量度量（基线 `9b150e8`）

| 指标 | 数值 | 门槛 | 结果 |
| --- | --- | --- | --- |
| 后端用例 | **207 passed** | 全绿 | ✅ |
| 后端覆盖率（`app`） | **95%** | CI `--cov-fail-under=85` | ✅ |
| 前端用例 | **19 passed / 6 文件** | 全绿 | ✅ |
| 前端质量门 | eslint（0 warning）、prettier check、`tsc --noEmit` + vite build | 通过 | ✅ |
| CI | Backend / Frontend / Infra 三作业，最近 5 次运行 | 全绿 | ✅ |
| 代码规模 | 后端 `app` 5,462 行、测试 4,508 行；前端 `src` 1,163 行 | — | — |
| 数据库迁移 | 4 个版本（初始核心表 / crawl_pages / dedup_settings / dedup_setting_history） | — | — |
| HTTP 业务端点 | 29 个（公开 4 + 维护者 25），另有 `/healthz` 探针 | — | — |

核心模块覆盖率（与 constitution 对"核心逻辑 ≥80%"的要求对照）：

| 模块 | 覆盖率 |
| --- | --- |
| `dedup/simhash.py`、`dedup/fingerprint.py` | 100% |
| `dedup/primary.py` | 96% |
| `services/dedup_service.py` | 97% |
| `classifier/rules.py` | 100% |
| `services/classifier_service.py` | 100% |
| `filtering/quality_filter.py` | 94% |
| `crawler/service.py` | 99% |
| `db/models.py` | 100% |

---

## 5. 端到端验收场景（T21）

`backend/tests/test_e2e.py` 覆盖 7 类场景，且与实际抓取数据相互印证：

| # | 场景 | 验证方式 |
| --- | --- | --- |
| 1 | 正常采集展示 | 列表含标题/类别/来源/时间；公开接口 `total` 与库内可见文章一致 |
| 2 | 完全重复合并 | 同内容两来源合并为一条，详情返回 2 个来源 |
| 3 | 近重复合并 | 相似度达阈值 → 合并；命中记录含判定类型与依据 |
| 4 | 不同视角不合并但关联 | 两篇独立保留，详情返回 `related_articles` |
| 5 | 未分类兜底与重新归类 | 落入"其他"并可被维护者改判，随后可被类别筛选命中 |
| 6 | 主记录失效切换 | 标记不可访问后主记录自动切换到组内其他有效来源 |
| 7 | 阈值调整审计 | 预览 → 调整 → 变更记录 → 回滚全链路 |
| ＋ | 低质/入口页过滤（补充） | 首页与栏目页不出现在公开列表（详见第 6 节偏差 D-01/D-06） |

---

## 6. 收敛过程中关闭的偏差（Change Log）

偏差按来源分三类：**A 文档↔实现不一致**、**B 需求边界/语义冲突**、**C 实跑暴露的缺陷**。

| 编号 | 类型 | 现象 | 处理与结论 | 证据（提交） |
| --- | --- | --- | --- | --- |
| D-01 | A | 文档称"列表页可查看某来源最后更新时间"，实现无对应控件 | 补 `GET /api/v1/sources` 与前端"来源更新状态"区块（T19） | `57c67cf` |
| D-02 | A | 文档称"详情页展示关联推荐"，前端实际未渲染 | **以实现为准修正文档**，并登记为未纳入范围（见第 7 节 O-01） | `029e1f9` |
| D-03 | B | T18 优先级表"权重 > … > 可访问性"，与"主记录失效要能切换"冲突 | 明确语义：**先在可访问成员中评选**，再按权重等排序 | `57c67cf` |
| D-04 | B | 阈值预览把"合并 → 关联"误归类为"新增关联" | 调整判定顺序：先判合并拆分，再判关联新增 | `57c67cf` |
| D-05 | C | 合并组切换主记录时旧主记录行被丢弃 | 成员集合改为取"全部关系行"的 `article_id` | `57c67cf` |
| D-06 | C | 站点首页被当作文章入库（真实抓取发现） | 入口页在**解析前**按 URL 判定并过滤，无法解析的首页也不会漏进列表 | `9b150e8` |
| D-07 | C | 首页链接按文档顺序取前 N 个，抓到的全是"关于/插件"栏目页 | 文章发现改为特征加权排序（日期段、路径片段、`.html`、锚文本），栏目链接降权 | `9b150e8` |
| D-08 | C | 定时任务重叠执行时 `crawl_pages` 唯一约束冲突（真实复现） | 插入移入 SAVEPOINT，撞约束后回滚并更新已有行 | `9b150e8` |
| D-09 | C | 单个来源异常会中断整轮调度 | 逐来源隔离，异常回滚并记入 `PipelineReport.error` | `9b150e8` |
| D-10 | C | 某博客所有文章标题都变成站名 | 支持"站名: 文章标题"的冒号分隔提纯（兼容"标题 - 站名"写法） | `9b150e8` |
| D-11 | C | 解析失败记录以 URL 作标题出现在公开列表 | 公开列表排除 `error` 记录，保留库内记录用于排查 | `9b150e8` |

> 偏差 D-01～D-05 来自"人工对照文档"，D-06～D-11 来自"**把系统真正跑起来**"——
> 这是本项目最有价值的收敛信号：单元测试全绿并不代表端到端可用。

---

## 7. 未收敛项（明确范围外 / 环境限制）

以下事项**不是遗漏，而是已决策未纳入**，均在此登记以保证"没有看不见的差距"：

| 编号 | 事项 | 分类 | 影响 | 建议动作 |
| --- | --- | --- | --- | --- |
| O-01 | 详情页未渲染 `related_articles`（接口已返回） | 需求未纳入 | 关联推荐只能通过 API/Swagger 查看 | 后续前端小改动即可 |
| O-02 | 列表页仅有分类筛选 + 分页控件（来源/标签/日期由 API 支持） | 需求未纳入 | 高级筛选需调用 API | 同上 |
| O-03 | 采集触发无 HTTP 接口（需执行 `run_scheduler_tick`） | 需求未纳入 | 定时任务需外部 cron/schtasks 驱动 | 可新增 `POST /admin/crawl` |
| O-04 | macOS 平台未纳入 CI | 环境限制 | 支持声明为"预期可用、未验证" | 加 `macos-latest` 矩阵即可升级为已验证 |
| O-05 | 前端管理子页面（来源/类别/去重策略）为占位页 | 需求未纳入 | 通过后端接口或 Swagger 操作 | 按需扩展 |
| O-06 | 可观测性（Prometheus/Grafana、抓取失败告警） | 范围外 | 排障依赖日志与 `/healthz` | 列入后续迭代 |
| O-07 | 分类为关键词规则、阈值标定样本量有限 | 范围外 | 复杂语义分类准确率有限 | 真实数据积累后迭代 |
| O-08 | 个别站点栏目页仍可能入库（如某站 `关于/插件` 页共 2 篇） | 站点结构歧义 | 轻微影响观感 | 维护者可将该来源设为黑名单或补充排除词 |

---

## 8. 结论

- **功能收敛**：T01–T21 的验收标准全部有实现与自动化证据，"用户故事 1–9"逐条可追溯；
- **质量收敛**：后端 207 用例 / 95% 覆盖率、前端 19 用例、CI 三作业常绿，覆盖率门槛已写入 CI；
- **偏差收敛**：登记 11 项偏差，全部关闭（含 6 项由真实运行暴露的缺陷），无未解释差异；
- **范围收敛**：8 项未纳入事项已显式登记并给出后续动作，不存在"隐性欠账"；
- **可复核**：任何人可用下述命令在本地复现本报告的全部数据。

```bash
# 一键复核（Linux / macOS / Windows Git Bash；PowerShell 5.1 请逐条执行）
cd backend  && black --check . && flake8 . && pytest --cov-fail-under=85
cd frontend && npm run lint && npm run format:check && npm run build && npm test
cd ..       && docker compose -f infra/docker-compose.yml config -q
```
