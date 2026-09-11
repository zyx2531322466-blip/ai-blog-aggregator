# 技术实现方案（Plan）

本文档基于 `spec.md` 中的功能需求，给出具体的技术实现方案，包括技术栈选择、架构设计与 API 契约。

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

### 通用错误响应格式
```
{
  "error": {
    "code": "NOT_FOUND",
    "message": "文章不存在"
  }
}
```
