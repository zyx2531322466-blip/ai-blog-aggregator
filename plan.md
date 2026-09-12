# 技术实现方案（Plan）

本文档基于 `spec.md` 中的功能需求，给出具体的技术实现方案，包括技术栈选择、架构设计与 API 契约。

> **版本 v2（客户新增需求）**：新增"订阅感兴趣方向 + 定期邮件推送"与"LLM Wiki 知识级去重"两项能力。
> 已确认的决策前提：**邮件推送** · **匿名订阅（邮箱 + 双确认）** · **全局知识库级去重** · **外部 LLM API**。
> 本文档第 7 节（技术栈）、第 8 节（架构）、第 9 节（API 契约）为 v2 增补内容（导航见文末"变更记录"）。

## 一、技术栈选择

### 后端
- **语言/框架**：Python + FastAPI
  - 理由：生态中有成熟的爬虫（Scrapy/httpx + BeautifulSoup）、NLP/分类（scikit-learn、sentence-transformers）与去重（simhash、datasketch）相关库，FastAPI 提供高性能异步 API 与自动生成的 OpenAPI 文档。
- **任务队列/调度**：Celery + Redis（或 APScheduler，视规模而定）
  - 用于周期性爬取任务、异步分类与去重处理，避免阻塞主服务。

### 爬虫与内容处理
- **抓取**：httpx / Scrapy，遵守目标站点 robots.txt。
- **内容解析**：readability-lxml 或 trafilatura，用于从原始 HTML 中提取正文、标题、发布时间等结构化信息。
- **去重**：
  - 精确去重：内容指纹（如 SHA-256 摘要）用于完全相同内容。
  - 近似去重：SimHash 或 MinLSH（datasketch）用于识别高度相似但非完全一致的内容。
- **分类**：
  - 初期：基于关键词/规则 + TF-IDF 分类器（scikit-learn），快速上线。
  - 后续可迭代为基于句向量（sentence-transformers）的语义分类或聚类，以提升准确性。

### 数据存储
- **主数据库**：PostgreSQL，存储文章元信息、分类结果、去重关系（原文与合并记录的映射）。
- **全文检索**：PostgreSQL 自带全文检索，或引入 Elasticsearch/Meilisearch（若检索需求复杂）。
- **缓存**：Redis，用于热门列表、分类聚合结果的缓存。

### 前端
- **框架**：React + TypeScript
  - 理由：组件化开发效率高，生态成熟，便于实现分类筛选、列表分页等交互。
- **样式**：Tailwind CSS，保证 `constitution.md` 中要求的界面一致性。

### 基础设施
- **容器化**：Docker + Docker Compose（开发环境），后续可迁移至 Kubernetes。
- **CI/CD**：GitHub Actions，执行 lint、测试、构建与部署流水线，满足 `constitution.md` 中的测试与代码质量门槛。
- **监控**：Prometheus + Grafana 监控爬取任务耗时、队列积压、API 响应时间等关键指标。

### 订阅与邮件推送（v2 新增）

| 关注点 | 选型 | 理由 |
| --- | --- | --- |
| 触达渠道 | **SMTP 邮件**（`smtplib` / `aiosmtplib`） | 无用户侧集成成本；本地开发可指向 Mailpit/MailHog 做邮件捕获，生产可平滑切换到托管服务（SES/Postmark 等），因此发送方抽象为接口 |
| 邮件内容渲染 | **Jinja2** 模板（HTML + 纯文本双版本） | 与"摘要卡片"结构契合；纯文本版本保证在禁用 HTML 的客户端仍可读 |
| 发送方抽象 | `MailSender` 协议 + `SmtpMailSender`（生产）/ `RecordingMailSender`（测试） | 遵循既有"外部依赖可注入"的测试策略：**测试中绝不真实发信** |
| 定时触发 | 复用既有调度入口（定时任务驱动），不引入 Celery 作为硬依赖 | 与现状一致（见 README「周期性采集的定时任务」）；规模增长后再评估迁移到 Celery/队列 |
| 幂等与限流 | 数据库唯一约束（订阅 × 文章）+ 每订阅串行执行 + 重试上限 | 推送必须"至多一次尝试、绝不重复打扰" |
| 退订与确认凭证 | 一次性随机 Token（哈希后存储）+ 有效期 | 无需账号体系即可安全确认/退订；避免明文凭证落库 |

### LLM Wiki 与知识级去重（v2 新增）

| 关注点 | 选型 | 理由 |
| --- | --- | --- |
| 知识点提炼 | **外部 LLM API**（OpenAI 兼容 `chat/completions`，可指向自建网关），要求返回 JSON | 结构化输出便于落库与校验；兼容接口便于更换供应商 |
| 结构化约束 | JSON Schema 校验 + 非法输出重试 + 解析失败降级为"待判定" | LLM 输出天然不稳定，必须做防御式解析 |
| 向量检索 | **pgvector** 扩展（`vector` 列 + 余弦距离索引 `ivfflat`/`hnsw`） | 复用既有 PostgreSQL，避免再引入独立向量库；数据量级适配 |
| 相似度判定 | 两级：向量召回 Top-K → 阈值判定，中间区间交 LLM 二次判定 | 兼顾成本与准确率；判定结论必须"保守" |
| 判定留痕 | `knowledge_decisions` 表记录命中条目、相似度、模型名、提示词版本 | 满足"可复核、可改判"与误筛抽检 |
| 人工优先 | 人工改判/废止条目写入优先级更高的标记 | 人工结论覆盖系统结论，并在后续判定中生效 |
| 成本控制 | 单篇/单轮 token 上限、批量大小、并发上限、结果缓存（按内容指纹） | 避免成本失控与配额耗尽 |
| 失败隔离 | LLM 超时/限流/配额不足 → 文章标记"待判定"，不阻塞采集、浏览、推送 | 与既有"单站点失败不中断整轮调度"的稳健性原则一致 |

## 二、架构设计

### 整体架构（分层/模块化）

```
┌─────────────────────────────────────────────────────────┐
│                      前端（React SPA）                    │
│         文章列表 / 分类筛选 / 详情页 / 管理后台            │
└───────────────────────────┬─────────────────────────────┘
                             │ REST API (HTTPS)
┌───────────────────────────▼─────────────────────────────┐
│                    API 服务（FastAPI）                    │
│   文章查询 / 分类查询 / 管理配置 / 鉴权（管理员接口）        │
└───────────────────────────┬─────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐   ┌────────────────┐   ┌─────────────────┐
│  PostgreSQL    │   │     Redis       │   │  任务队列(Celery) │
│ 文章/分类/去重  │   │  缓存/队列broker │   │  异步任务执行器    │
└───────────────┘   └────────────────┘   └─────────┬────────┘
                                                    │
                          ┌─────────────────────────┼─────────────────────────┐
                          ▼                         ▼                         ▼
                 ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
                 │   爬虫任务模块    │      │   分类处理模块    │      │   去重处理模块    │
                 │ 定时/触发式抓取   │ ---> │ 规则/模型分类     │ ---> │ 指纹计算与比对    │
                 └─────────────────┘      └─────────────────┘      └─────────────────┘
```

### 数据流

1. **采集阶段**：调度器周期性触发爬虫任务 → 抓取目标站点 → 解析正文与元信息 → 写入"待处理"队列。
2. **处理阶段**：分类模块对新内容打标签 → 去重模块计算指纹并与历史内容比对 → 若判定为重复，建立"合并关系"记录；若不重复，写入正式文章表。
3. **服务阶段**：API 服务从数据库读取已处理内容，按分类/时间/来源提供查询、筛选接口。
4. **展示阶段**：前端调用 API 渲染列表与详情页，去重合并的文章展示所有来源出处。
5. **知识整理阶段（v2）**：对通过"完全重复 / 近重复"去重后的文章，调用 LLM 提炼知识点 →
   与知识 Wiki 比对 → 判定"全新 / 已覆盖 / 部分新增" → 已覆盖者归档、部分新增者补写 Wiki。
6. **订阅推送阶段（v2）**：按订阅节奏扫描"本期新增 + 命中订阅方向 + 未被知识去重筛掉 + 未推送过"的文章 →
   渲染摘要邮件 → 通过 SMTP 投递 → 记录投递结果与已推送清单（保证不重复）。

> **顺序约束**：第 5 步必须在第 6 步之前完成，否则会把"知识已覆盖"的文章误推给用户；
> 因此推送生成阶段对"待判定"文章采取**跳过并留待下期**的策略，而不是直接推送。

### v2 增量架构（订阅推送 + 知识去重）

```
                       既有流水线：抓取 → 解析 → 过滤 → 分类 → 文本级去重（完全/近重复）
                                                          │
                                                          ▼
                                        ┌───────────────────────────────────┐
                                        │   KnowledgePipeline（新增）        │
                                        │  1) KnowledgeExtractor  知识点提炼 │
                                        │  2) VectorIndex(pgvector) 向量检索 │
                                        │  3) KnowledgeMatcher   覆盖判定    │
                                        │  4) WikiService        条目维护    │
                                        │  5) 判定留痕 knowledge_decisions   │
                                        └───────────────┬───────────────────┘
                                  全新/部分新增 │       │ 已覆盖 → 归档（不进列表/不推送）
                                                ▼       ▼
                                        ┌───────────────────────────────────┐
                                        │   DigestPipeline（新增）           │
                                        │  1) 订阅方向匹配 subscription_*    │
                                        │  2) 组装本期条目（排除已推送）      │
                                        │  3) Jinja2 渲染 HTML/纯文本        │
                                        │  4) MailSender(SMTP) 投递 + 记录   │
                                        └───────────────┬───────────────────┘
                                                        ▼
                                            订阅者邮箱（含确认/退订链接）
```

### 关键模块划分（对应 constitution.md 的模块化要求）

| 模块 | 职责 |
|---|---|
| Crawler Service | 站点发现、抓取、限流与礼貌性控制 |
| Parser | HTML 结构化解析，提取标题/正文/时间 |
| Classifier | 内容分类打标 |
| Deduplicator | 精确/近似去重判定与合并关系维护 |
| Content API | 面向前端的查询、筛选接口 |
| Admin API | 面向维护者的采集范围配置、效果监控接口 |
| Web Frontend | 用户浏览界面 |
| **SubscriptionService**（v2） | 订阅创建/确认/退订/偏好维护、反滥用与凭证管理 |
| **DigestService**（v2） | 方向匹配、本期条目组装、排序截断、模板渲染、投递编排 |
| **MailSender**（v2） | 邮件发送抽象（SMTP 实现 / 测试用记录实现），含重试与投递记录 |
| **KnowledgeExtractor**（v2） | 调用 LLM 把文章提炼为结构化知识点（JSON 校验 + 重试） |
| **KnowledgeMatcher**（v2） | 向量召回 + 阈值/二次判定，产出"全新 / 已覆盖 / 部分新增"结论 |
| **WikiService**（v2） | 知识点条目维护（新增/编辑/废止/合并）、人工改判、条目与文章关联 |
| **Knowledge Admin API**（v2） | 判定复核、误筛统计、Wiki 管理、LLM 用量与失败率查询 |

## 三、API 契约

以下为核心 REST API 定义（详细字段类型以 OpenAPI/Swagger 自动生成文档为准，此处列出关键接口）。

### 1. 获取文章列表
```
GET /api/v1/articles
Query 参数:
  - category: string（可选，按分类筛选）
  - source: string（可选，按来源筛选）
  - start_date / end_date: string(ISO 8601，可选)
  - page: int（默认 1）
  - page_size: int（默认 20）

响应 200:
{
  "total": 128,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": "article_123",
      "title": "文章标题",
      "summary": "文章摘要",
      "category": ["技术", "AI"],
      "published_at": "2026-09-01T10:00:00Z",
      "primary_source": {
        "name": "来源站点名",
        "url": "https://example.com/post/123"
      },
      "merged_sources_count": 2
    }
  ]
}
```

### 2. 获取文章详情（含去重合并来源）
```
GET /api/v1/articles/{article_id}

响应 200:
{
  "id": "article_123",
  "title": "文章标题",
  "content": "正文内容（或正文摘要，视展示策略而定）",
  "category": ["技术", "AI"],
  "published_at": "2026-09-01T10:00:00Z",
  "sources": [
    { "name": "站点A", "url": "https://a.com/post/1", "crawled_at": "..." },
    { "name": "站点B", "url": "https://b.com/repost/1", "crawled_at": "..." }
  ]
}
```

### 3. 获取分类列表
```
GET /api/v1/categories

响应 200:
{
  "categories": [
    { "name": "技术", "article_count": 45 },
    { "name": "AI", "article_count": 30 }
  ]
}
```

### 4. 管理员：配置采集范围（需鉴权）
```
POST /api/v1/admin/sources
Headers: Authorization: Bearer <token>
Body:
{
  "url": "https://newsite.com",
  "topics": ["AI", "技术"]
}

响应 201:
{ "id": "source_45", "status": "active" }
```

### 5. 管理员：查看分类/去重效果概览（需鉴权）
```
GET /api/v1/admin/insights
Headers: Authorization: Bearer <token>

响应 200:
{
  "category_distribution": { "技术": 45, "AI": 30, "未分类": 5 },
  "dedup_stats": {
    "total_crawled": 500,
    "unique_articles": 320,
    "merged_duplicates": 180
  }
}
```

### 6. 公开：可订阅方向清单（v2）
```
GET /api/v1/subscription-topics
（无需鉴权；用于订阅页渲染可选方向）

响应 200:
{
  "categories": [ { "value": "AI/机器学习", "article_count": 30 } ],
  "tags":       [ { "value": "Kubernetes",  "article_count":  8 } ],
  "sources":    [ { "id": "source_45", "name": "示例博客", "site_url": "https://blog.example.com/" } ],
  "frequencies": ["daily", "weekly"]
}
```

### 7. 公开：创建订阅（v2，匿名 + 双确认）
```
POST /api/v1/subscriptions
Content-Type: application/json
Body:
{
  "email": "reader@example.com",
  "topics": [
    { "type": "category", "value": "AI/机器学习" },
    { "type": "tag",      "value": "Kubernetes" },
    { "type": "source",   "value": "source_45" },
    { "type": "keyword",  "value": "向量数据库" }
  ],
  "frequency": "weekly",          // daily | weekly（缺省取全局默认）
  "max_items": 10                 // 可选，1..N，缺省取全局默认
}

响应 202（需用户到邮箱确认后才生效）:
{
  "id": "sub_88",
  "status": "pending_confirmation",
  "confirm_expires_at": "2026-09-13T15:00:00Z",
  "message": "确认邮件已发送，请在有效期内点击邮件中的确认链接"
}

错误:
- 400 VALIDATION_ERROR  邮箱格式非法 / topics 为空 / max_items 超范围
- 409 ALREADY_SUBSCRIBED 同一邮箱存在"已确认"的相同方向订阅
- 429 RATE_LIMITED      同一邮箱或来源 IP 短时间内重复提交
```

### 8. 公开：确认、退订、自助查询与删除（v2）
```
GET  /api/v1/subscriptions/confirm?token=<confirm_token>
  → 200 { "id": "sub_88", "status": "confirmed", "confirmed_at": "..." }
  → 410 CONFIRM_TOKEN_EXPIRED   凭证过期（可重新发起订阅）
  → 404 CONFIRM_TOKEN_INVALID   凭证无效

POST /api/v1/subscriptions/unsubscribe
Body: { "token": "<unsubscribe_token>", "scope": "self" }   // self=仅本方向；all=全部订阅
  → 200 { "status": "unsubscribed", "unsubscribed_at": "..." }   // 立即生效，无需登录

GET  /api/v1/subscriptions/me?token=<unsubscribe_token>
  → 200 { "email": "re***@example.com", "frequency": "weekly", "topics": [...], "status": "confirmed" }

DELETE /api/v1/subscriptions/me
Body: { "token": "<unsubscribe_token>" }
  → 204   删除订阅及其偏好数据（满足"可删除个人数据"）
```

### 9. 维护者：订阅与推送管理（v2，需鉴权）
```
GET   /api/v1/admin/subscriptions?status=&frequency=&page=&page_size=
  → 200 { "total": 120, "items": [ { "id": "sub_88", "email": "re***@example.com",
             "status": "confirmed", "frequency": "weekly", "topic_count": 3,
             "last_sent_at": "...", "created_at": "..." } ] }     // 邮箱脱敏

GET   /api/v1/admin/digests?subscription_id=&status=&page=
  → 200 { "total": 300, "items": [ { "id": "digest_9", "subscription_id": "sub_88",
             "period_start": "...", "period_end": "...", "item_count": 7,
             "status": "sent|failed|skipped_empty", "sent_at": "...", "error": null } ] }

GET   /api/v1/admin/digests/{digest_id}
  → 200 { ...摘要元信息..., "items": [ { "article_id": "article_1", "position": 1,
             "matched_topics": ["category:AI/机器学习"], "title": "...", "url": "..." } ] }

POST  /api/v1/admin/digests/run          // 手动触发一轮（可指定 subscription_id 做单订阅重跑）
Body: { "subscription_id": "sub_88", "dry_run": true }
  → 200 { "generated": 3, "sent": 2, "skipped_empty": 1, "failed": 0 }   // dry_run 只生成不投递

GET   /api/v1/admin/notification-settings
PATCH /api/v1/admin/notification-settings
Body: {
  "default_frequency": "weekly",
  "send_window": { "start_hour": 9, "end_hour": 21, "timezone": "Asia/Shanghai" },
  "max_items_per_digest": 10,
  "send_empty_digest": false,
  "max_retries": 3
}
  → 200 { ...生效后的设置... }
```

### 10. 维护者：知识 Wiki 管理（v2，需鉴权）
```
GET   /api/v1/admin/wiki/entries?status=active&query=&page=
  → 200 { "total": 320, "items": [ { "id": "wiki_12", "name": "Raft 选主流程",
             "summary": "...", "status": "active", "created_by": "llm",
             "source_article_ids": ["article_1", "article_9"], "updated_at": "..." } ] }

POST  /api/v1/admin/wiki/entries            // 人工新增条目
Body: { "name": "Raft 选主流程", "summary": "...", "source_article_ids": ["article_1"], "note": "人工整理" }
  → 201 { "id": "wiki_12", "status": "active" }

PATCH /api/v1/admin/wiki/entries/{entry_id} // 编辑条目（名称/摘要/备注/支撑文章）
  → 200 { ...更新后的条目... }

POST  /api/v1/admin/wiki/entries/{entry_id}/retire   // 废止（不再作为覆盖依据）
  → 200 { "id": "wiki_12", "status": "retired" }

POST  /api/v1/admin/wiki/entries/merge               // 合并条目
Body: { "source_entry_ids": ["wiki_12", "wiki_13"], "target": { "name": "...", "summary": "..." } }
  → 200 { "id": "wiki_20", "status": "active", "merged_from": ["wiki_12", "wiki_13"] }
```

### 11. 维护者：知识判定复核与改判（v2，需鉴权）
```
GET  /api/v1/admin/knowledge-decisions?decision=covered&page=
  → 200 { "total": 45, "items": [ { "id": "kd_7", "article_id": "article_55",
             "decision": "covered|new_knowledge|partial|pending",
             "matched_entry_id": "wiki_12", "similarity": 0.91,
             "rationale": "与条目『Raft 选主流程』描述一致，未发现新增主张",
             "model": "gpt-4o-mini", "prompt_version": "knowledge-v1",
             "actor": "system", "created_at": "..." } ] }

POST /api/v1/admin/articles/{article_id}/knowledge-override
Body: { "decision": "new_knowledge", "reason": "该文包含实测数据，属于新增信息" }   // 人工结论优先
  → 200 { "article_id": "article_55", "decision": "new_knowledge", "actor": "human" }

GET  /api/v1/admin/knowledge-stats
  → 200 {
         "filtered_total": 45,
         "by_category": { "AI/机器学习": 20, "数据库": 25 },
         "pending_total": 3,
         "llm_usage": { "calls_today": 210, "failures_today": 2, "tokens_today": 180000 }
       }
```

### 12. 既有接口的字段扩展（v2）
```
GET /api/v1/articles        // 列表项新增字段
  "knowledge_status": "new|partial|covered|pending",   // covered 的文章默认不出现在列表
  "knowledge_points": ["Raft 选主流程", "日志压缩"]

GET /api/v1/articles/{id}   // 详情新增字段
  "knowledge": {
    "status": "partial",
    "points": [ { "name": "Raft 选主流程", "wiki_entry_id": "wiki_12", "is_new": false },
                { "name": "选主超时的实测数据", "wiki_entry_id": null, "is_new": true } ],
    "decision_reason": "..."
  }
```

### 通用错误响应格式
```
{
  "error": {
    "code": "NOT_FOUND",
    "message": "文章不存在"
  }
}
```

### v2 新增错误码
| code | HTTP | 含义 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 400 | 邮箱格式、方向类型、条数上限等参数非法 |
| `ALREADY_SUBSCRIBED` | 409 | 同一邮箱已存在相同方向的“已确认”订阅 |
| `RATE_LIMITED` | 429 | 订阅/确认/退订请求过于频繁（反滥用） |
| `CONFIRM_TOKEN_INVALID` | 404 | 确认凭证无效 |
| `CONFIRM_TOKEN_EXPIRED` | 410 | 确认凭证过期，可重新发起订阅 |
| `UNSUBSCRIBE_TOKEN_INVALID` | 404 | 退订/自助查询凭证无效 |
| `KNOWLEDGE_PENDING` | 202 | 知识点仍在“待判定”（LLM 暂不可用），已排队重试 |
| `LLM_UNAVAILABLE` | 503 | 维护者触发知识判定时外部 LLM 不可用 |
| `WIKI_ENTRY_CONFLICT` | 409 | 合并条目时目标与来源冲突（如条目已废止） |

---

## 四、数据模型（v2 新增表）

> 命名与既有约定一致：字符串主键（前缀 + uuid）、`created_at/updated_at`、枚举以小写英文值落库。
> 迁移使用 Alembic（PostgreSQL 生产 / SQLite 本地），向量列仅在 PostgreSQL 启用（本地降级为关键词相似度）。

### 4.1 订阅与推送

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `subscriptions` | id, email, status(`pending_confirmation/confirmed/unsubscribed`), frequency(`daily/weekly`), max_items, confirm_token_hash, confirm_expires_at, unsubscribe_token_hash, created_at, confirmed_at, unsubscribed_at, last_sent_at | 匿名订阅主体；**邮箱与凭证哈希**存储；凭证一次性可用 |
| `subscription_topics` | id, subscription_id, topic_type(`category/tag/source/keyword`), topic_value | 订阅方向集合；同一订阅内 `(type,value)` 唯一 |
| `digests` | id, subscription_id, period_start, period_end, status(`pending/sent/failed/skipped_empty`), item_count, sent_at, error, created_at | 每次推送（或跳过）的记录；唯一约束 `(subscription_id, period_start, period_end)` 保证可重入不重复发送 |
| `digest_items` | id, digest_id, article_id, position, matched_topics(JSON) | 本期条目；唯一约束 `(subscription_id, article_id)` 由 `digests` 联表保证“同一文章不重复推送” |
| `notification_settings` | key(PK), value | 全局推送设置（默认节奏、发送时间窗、单封上限、空期是否发送、重试上限），沿用既有设置表模式并记录变更历史 |

### 4.2 知识 Wiki 与判定

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `wiki_entries` | id, name, summary, status(`active/retired/merged`), created_by(`llm/human`), merged_into_id, embedding(vector, 可空), human_note, created_at, updated_at | 知识点条目；仅 `active` 参与覆盖判定 |
| `wiki_entry_sources` | entry_id, article_id | 条目与支撑文章的多对多关联（可追溯“这个知识点来自哪些文章”） |
| `knowledge_decisions` | id, article_id, decision(`new_knowledge/covered/partial/pending`), matched_entry_id, similarity, rationale, model, prompt_version, actor(`system/human`), created_at | 判定留痕；`actor=human` 的记录优先级最高并以最新一条为准 |

### 4.3 既有表的状态扩展

- `articles.status` 增加 `knowledge_duplicate`（知识已覆盖，归档，不出现在列表与推送）；
- 新增 `articles.knowledge_status`（`new/partial/covered/pending`，用于列表/详情字段与推送过滤）；
- 文章与知识点的关联通过 `knowledge_decisions` + `wiki_entry_sources` 表达，避免在文章表冗余存放大对象。

---

## 五、关键规则与失败处理（v2）

### 5.1 方向匹配规则

- 一篇文章命中订阅方向集合中**任意一条**即视为相关：类别、标签、来源直接比对；
  关键词对**标题 + 摘要**做包含匹配（大小写与全半角归一化后比较）。
- 匹配结果记录在 `digest_items.matched_topics`，便于用户与维护者理解“为什么推给我”。
- 未分类（“其他”）文章只有在其命中标签/来源/关键词时才可能被推送，避免把兜底内容推给所有人。

### 5.2 知识去重判定规则（保守优先）

| 相似度区间 | 判定 | 处理 |
| --- | --- | --- |
| ≥ 高阈值（默认 0.92） | **已覆盖** | 归档；记录命中条目与相似度；不进入列表与推送 |
| 中间区间（默认 0.80–0.92） | 交 **LLM 二次判定**：仅当明确“无新增信息”才判“已覆盖”，否则判“部分新增/全新” | 记录二次判定理由 |
| < 0.80 | **全新知识** | 正常展示，并把提炼出的知识点写入 Wiki（状态 active） |
| LLM 不可用 / 超时 / 限流 | **待判定（pending）** | 不推送、不归档；下一轮重试；不影响浏览 |

> 与既有原则一致：**误筛比漏筛严重**——知识级误筛会让用户“看不到内容”，因此所有不确定情况一律不筛。
> 三个阈值与是否启用知识去重均为维护者可配置项（沿用 `dedup_settings` 的可审计 + 可回滚模式）。

### 5.3 与既有去重的优先级

```
文本级：完全重复（SHA-256）→ 近重复（SimHash ≥ 阈值）      // 先合并，避免对重复文本重复调用 LLM
       ↓ 通过后
知识级：知识点提炼 → Wiki 匹配 → 全新 / 部分新增 / 已覆盖    // 本层只“归档”，不合并关系
```

- 知识级判定**不修改**既有的合并组与主记录选择逻辑（两层职责分离，互不干扰）；
- 被知识去重归档的文章仍可通过维护者接口查看与改判，绝不物理删除。

### 5.4 幂等、重试与成本

- **幂等**：`digests` 的周期唯一约束 + `digest_items` 的文章唯一约束，保证任务重跑不会重复打扰用户；
- **重试**：发送失败按 `max_retries` 重试并在窗口内退避；超过上限记录为 failed 并纳入维护者视图；
- **成本**：LLM 调用按内容指纹缓存（同一文章只提炼一次）、限制单轮调用数与并发；
  维护者可查询当日调用量、失败率与 token 消耗；配额耗尽时自动降级为“待判定”。

### 5.5 隐私与合规

- 只收集**邮箱 + 订阅偏好**；凭证以哈希存储；提供凭凭证自助查询与删除；
- 每封邮件包含发送者说明与退订链接；严格遵守“仅向已确认地址发送”；
- 文章内容会发送给外部 LLM 服务用于知识点提炼，此事实在站点说明中披露；**订阅者邮箱不参与 LLM 调用**。

---

## 六、配置项（v2 环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_MAIL_ENABLED` | `false` | 是否真实发信（测试与本地默认关闭） |
| `APP_SMTP_HOST` / `APP_SMTP_PORT` / `APP_SMTP_USER` / `APP_SMTP_PASSWORD` / `APP_SMTP_USE_TLS` | — | SMTP 连接参数 |
| `APP_MAIL_FROM` | `no-reply@example.com` | 发件人（需与发信域名的 SPF/DKIM 一致） |
| `APP_PUBLIC_BASE_URL` | `http://localhost:3000` | 用于生成确认/退订链接（必须对外可达） |
| `APP_DIGEST_DEFAULT_FREQUENCY` | `weekly` | 默认推送节奏 |
| `APP_DIGEST_MAX_ITEMS` | `10` | 单封邮件最大条数 |
| `APP_DIGEST_SEND_WINDOW` | `09:00-21:00` | 发送时间窗（避免深夜打扰） |
| `APP_LLM_BASE_URL` / `APP_LLM_API_KEY` / `APP_LLM_MODEL` | — | OpenAI 兼容接口地址、密钥与模型名 |
| `APP_LLM_TIMEOUT_SECONDS` | `30` | 单次调用超时 |
| `APP_LLM_MAX_CALLS_PER_RUN` | `200` | 单轮知识点提炼调用上限（成本闸门） |
| `APP_KNOWLEDGE_ENABLED` | `false` | 是否启用知识级去重（默认关闭，先观察再开启） |
| `APP_KNOWLEDGE_SIMILARITY_HIGH` | `0.92` | “已覆盖”阈值 |
| `APP_KNOWLEDGE_SIMILARITY_LOW` | `0.80` | 进入二次判定的下限 |
| `APP_KNOWLEDGE_PROMPT_VERSION` | `knowledge-v1` | 提示词版本（随判定留痕写入） |

---

## 七、测试策略（v2）

| 对象 | 策略 |
| --- | --- |
| 订阅生命周期 | 创建/确认/过期/退订/重复提交的完整路径 + 反滥用频控边界 |
| 方向匹配 | 类别/标签/来源/关键词各自命中与不命中的组合；未分类文章的边界 |
| 摘要生成 | 周期边界（含无更新）、条数截断、排序稳定性、被合并文章只出现一次 |
| 幂等 | 任务重跑不重复发送；同一文章不重复进入不同 digest |
| 邮件发送 | 使用 `RecordingMailSender` 断言渲染结果与收件人；**测试中禁止真实发信**；失败与重试路径用可编程失败注入 |
| LLM 提炼 | 用录制响应替身（fixture）覆盖正常 JSON、非法 JSON、超时、限流四类情形，**不访问真实 API** |
| 知识判定 | 固定样本集（全新/已覆盖/部分新增）+ 阈值边界（高/中/低）断言；`pending` 状态不推送 |
| 人工优先 | 改判与条目废止后，后续同类判定遵循人工结论 |
| 回归 | 既有 T01–T21 能力测试必须全绿（知识去重与订阅不得改变既有列表/详情/去重语义） |

---

## 八、变更记录（v2）

| 版本 | 变更 | 章节 |
| --- | --- | --- |
| v1 | 技术栈、架构设计、API 契约（采集/分类/去重/浏览/维护） | 一、二、三（第 1–5 节） |
| v2 | 技术栈补充（SMTP/LLM/pgvector）、架构与数据流补充、API 契约新增第 6–12 节、数据模型（第四–八节） | 一~八 |
