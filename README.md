# AI 博客聚合站 · ai-blog-aggregator

[![CI](https://github.com/zyx2531322466-blip/ai-blog-aggregator/actions/workflows/ci.yml/badge.svg)](https://github.com/zyx2531322466-blip/ai-blog-aggregator/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688)
![React](https://img.shields.io/badge/React-18-61DAFB)
![Node](https://img.shields.io/badge/Node-%E2%89%A520-339933)

自动抓取多个技术博客，完成**解析清洗 → 低质过滤 → 自动分类打标 → 跨来源去重与事件关联 → 统一浏览**，
并为维护者提供**来源配置、类别治理、去重策略审计与效果概览**的一站式后台。

---

## 目录

- [核心能力](#核心能力)
- [技术栈](#技术栈)
- [系统流程](#系统流程)
- [支持的系统](#支持的系统)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [接口一览](#接口一览)
- [网站使用说明](#网站使用说明)
- [核心规则说明](#核心规则说明)
- [数据模型](#数据模型)
- [测试与质量门槛](#测试与质量门槛)
- [CI](#ci)
- [常见问题](#常见问题)
- [AI 开发过程](#ai-开发过程)
- [项目文档](#项目文档)
- [抓取合规说明](#抓取合规说明)

---

## 核心能力

| 领域 | 能力 |
| --- | --- |
| 来源管理 | 主题/关注领域配置，来源黑/白名单，权重与更新频率（高频 3h / 普通 24h / 低频 7d / 自定义） |
| 采集 | 遵守 `robots.txt`、礼貌限速、按“文章特征”加权的同域文章发现、原始 HTML 留存、失败不中断批次、并发抓取安全 |
| 解析 | 标题/正文/发布时间/作者抽取，支持 Open Graph、`<article>`、JSON-LD 等多种页面结构 |
| 质量控制 | 排除词命中、广告话术、导航/聚合页（链接密度）、内容过短等低质内容过滤 |
| 分类与标签 | 受控类别体系 + 关键词权重打分，多标签，无法归类的落入"其他"并标记为未分类 |
| 去重与关联 | SHA-256 完全重复识别、SimHash 近重复识别（阈值可调）、同事件不同视角文章关联推荐 |
| 合并治理 | 合并组全部来源与原文链接展示、主记录按优先级自动选择与失效切换、可回滚的策略审计 |
| 浏览 | 文章列表（分类筛选 + 分页；来源/标签/日期筛选由接口支持）、详情页（全部来源原文链接、发布时间与采集时间）；关联推荐由详情接口返回 |
| 维护者后台 | 效果概览（分类分布、三类去重命中统计）、来源配置、类别管理、去重策略管理入口 |
| 访问控制 | 维护者 Bearer Token 单令牌模型（非用户账户体系），统一错误响应格式 |

---

## 技术栈

**后端**：Python 3.10 · FastAPI · SQLAlchemy 2.0（`Mapped` 类型化映射）· Alembic · Pydantic v2 · pydantic-settings · httpx · BeautifulSoup4/lxml

**数据**：SQLite（本地与测试默认）· PostgreSQL 16（Docker/生产）· Redis 7（预留）

**前端**：React 18 · TypeScript 5 · Vite 5 · Tailwind CSS 3 · react-router-dom 6 · Vitest + Testing Library

**工程化**：black / flake8 / pytest + pytest-cov（后端），eslint / prettier / tsc / vitest（前端），GitHub Actions CI，Docker Compose

---

## 系统流程

```mermaid
flowchart LR
    A[来源配置<br/>黑白名单 · 权重 · 频率] --> B[调度器<br/>到期判定]
    B --> C[抓取<br/>robots · 限速 · 文章发现]
    C --> D[解析<br/>标题 · 正文 · 时间 · 作者]
    D --> E{质量过滤}
    E -- 低质/排除词命中 --> X[标记 filtered<br/>不进入正式文章表]
    E -- 通过 --> F[分类与打标]
    F --> G{去重判定}
    G -- 完全重复 --> H[合并组 · 主记录]
    G -- 近重复 ≥ 阈值 --> H
    G -- 相似 < 阈值且 ≥ 0.5 --> I[关联推荐]
    G -- 无命中 --> J[独立文章]
    H --> K[列表 / 详情展示]
    I --> K
    J --> K
    K --> L[维护者概览与治理]
```

单位来源的一次处理流程封装在 `app/services/pipeline_service.process_source`（抓取 → 解析 → 过滤 → 分类 → 去重），
由调度器 `app/services/scheduler_service.run_due_sources` 按各来源频率周期触发。

---

## 目录结构

```
.
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/             # 公开接口 + 维护者 admin 接口
│   │   ├── classifier/         # 关键词分类规则
│   │   ├── core/               # 配置、统一错误、鉴权
│   │   ├── crawler/            # 抓取器、robots、限速、文章发现、采集服务
│   │   ├── db/                 # 模型、枚举、会话、迁移基类
│   │   ├── dedup/              # 指纹、SimHash、主记录选择规则
│   │   ├── filtering/          # 低质量/不相关内容过滤
│   │   ├── parser/             # HTML 正文与元信息解析
│   │   ├── scheduler/          # 更新频率档位与到期判定
│   │   ├── scripts/            # 种子数据脚本（热门博客来源）
│   │   ├── schemas/            # Pydantic 请求/响应模型
│   │   └── services/           # 业务编排（文章/类别/来源/去重/概览/调度/流水线）
│   ├── alembic/                # 数据库迁移
│   ├── tests/                  # pytest 测试（含 HTML fixture，绝不访问真实网络）
│   ├── Dockerfile
│   └── requirements*.txt
├── frontend/                   # React + TypeScript + Tailwind 前端
│   ├── src/
│   │   ├── api/                # 接口封装与类型
│   │   ├── components/         # 卡片、筛选、分页、来源新鲜度等
│   │   └── pages/              # 列表页、详情页、维护者概览页
│   ├── nginx.conf              # 生产静态资源 + /api 反向代理
│   └── Dockerfile
├── docs/
│   └── sharing-guide.md        # 让其他人访问站点（局域网/临时公网/长期部署）
├── infra/
│   ├── docker-compose.yml      # db(PostgreSQL) + redis + api + web
│   └── .env.example
├── .github/workflows/ci.yml    # 后端 / 前端 / 基础设施三段式 CI
├── constitution.md             # 项目治理原则（最高优先级）
├── spec.md                     # 需求规格
├── plan.md                     # 技术方案
├── tasks.md                    # 任务拆解
├── tickets.md                  # T01–T21 逐票实现说明
└── README.md
```

---

## 支持的系统

| 系统 | 支持状态 | 验证方式 | 说明 |
| --- | --- | --- | --- |
| **Windows 10 / 11** | ✅ 已支持（已验证） | 本仓库开发环境为 Windows 11，后端 207 个测试、black/flake8、前端 lint/build/test 均在本机通过 | PowerShell 7、Git Bash、WSL2 三种终端均可；容器方式需 Docker Desktop |
| **Linux（x86_64）** | ✅ 已支持（已验证） | CI 每次 push 在 `ubuntu-latest` 上执行全部质量门（后端测试 + 覆盖率、前端 lint/build/test、compose 校验） | 建议 Python 3.10+；容器方式需 Docker Engine + `docker compose` 插件 |
| **macOS（Intel / Apple Silicon）** | ⚠️ 预期可用，**未验证** | 未纳入 CI，无实测记录 | 代码无平台相关分支（不使用 `fcntl` / `os.name` / `subprocess` 等），依赖无平台条件标记，理论上可直接运行；若遇到问题欢迎提 issue |
| 其他系统（FreeBSD、32 位平台等） | ❌ 不支持 | — | 未验证，也未提供安装说明 |

> **结论**：正式支持的平台是 **Windows 与 Linux**（均为已验证）；**macOS 预期可用但未经官方验证**；其余系统不支持。

补充说明：

- 后端为纯 Python 3.10 实现，未使用任何平台相关 API；数据库默认 SQLite（跨平台），容器方案使用 PostgreSQL 16；
- 前端是浏览器应用，本身与操作系统无关，差异只出现在**命令行操作**上（见下文各系统的命令）；
- 可用以下命令自行复核平台无关性：

  ```bash
  grep -rInE "fcntl|sys\.platform|os\.name|platform\.system|multiprocessing|subprocess" backend/app   # 预期无输出
  ```

---

## 快速开始

> 想把自己搭好的站点**分享给别人**（同一局域网 / 临时公网链接 / 长期公网部署）？
> 见独立手册 **[让其他人访问你的站点](docs/sharing-guide.md)**。
>
> 想让站点立刻**有内容可看**（写入 12 个热门技术博客并抓取一次）：
> `docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed_sources`

### 方式一：Docker Compose（Windows / Linux / macOS 通用）

> 前置条件：Windows 与 macOS 需安装 **Docker Desktop**；Linux 需 **Docker Engine + `docker compose` 插件**。
> 该方式下三个系统的启动命令完全一致，只有"复制环境变量文件"这一句的写法不同。

**Linux / macOS / Windows Git Bash / WSL2：**

```bash
cp infra/.env.example infra/.env      # 按需修改端口/令牌
docker compose -f infra/docker-compose.yml up --build
```

**Windows PowerShell：**

```powershell
Copy-Item infra\.env.example infra\.env
docker compose -f infra/docker-compose.yml up --build
```

启动后（三系统一致）：

- 前端：<http://localhost:3000>
- 后端 API：<http://localhost:8000>，交互式文档 <http://localhost:8000/docs>
- 健康探针：<http://localhost:8000/healthz>

`api` 容器启动时会先执行 `alembic upgrade head` 完成数据库迁移，再启动服务。

### 方式二：本地开发

三系统都需要：**Python 3.10+**、**Node.js ≥ 20（推荐 22 LTS）**。后端默认使用 SQLite，无需额外安装数据库。

#### Windows

推荐使用 **PowerShell 7** 或 **Git Bash**；WSL2 中按 Linux 章节操作。

```powershell
# 1) 后端（PowerShell）
cd backend
py -3.10 -m venv .venv                       # 若无 py 启动器，改用 python -m venv .venv
.\.venv\Scripts\Activate.ps1                 # 若提示禁止运行脚本：
                                             # Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install -r requirements-dev.txt
New-Item -ItemType Directory -Force data | Out-Null   # SQLite 文件目录，必需
python -m alembic upgrade head                # 初始化表结构
"APP_ADMIN_TOKEN=dev-token" | Set-Content -Encoding utf8 .env   # 也可手写 backend\.env
python -m uvicorn app.main:app --reload
```

Git Bash / cmd 下的等价写法：

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate                 # cmd：.venv\Scripts\activate.bat
python -m pip install -r requirements-dev.txt
mkdir -p data
python -m alembic upgrade head
APP_ADMIN_TOKEN=dev-token python -m uvicorn app.main:app --reload
```

#### Linux

```bash
# 1) 后端（bash）
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
mkdir -p data                                 # SQLite 文件目录，必需
python -m alembic upgrade head                # 初始化表结构
APP_ADMIN_TOKEN=dev-token python -m uvicorn app.main:app --reload
```

> Debian/Ubuntu 若缺少 `python3-venv`：`sudo apt install python3.10-venv`。

#### macOS

与 Linux 完全一致（`bash` / `zsh` 均可）。若系统自带 Python 版本过低：

```bash
brew install python@3.10
python3.10 -m venv .venv
```

Apple Silicon 无需额外配置，`lxml`、`psycopg2-binary` 等依赖均提供 arm64 wheel。

#### 前端（Windows / Linux / macOS 命令一致）

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173，/api 默认代理到 http://localhost:8000
```

> 仓库内 `frontend/.npmrc` 已将 registry 指向国内镜像；如需切换可自行修改或删除该文件。
> 代理到其他后端地址：`VITE_API_PROXY_TARGET=http://localhost:9000 npm run dev`（PowerShell：`$env:VITE_API_PROXY_TARGET="http://localhost:9000"; npm run dev`）。

### 冒烟验证

**Linux / macOS / Git Bash / WSL2：**

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/api/v1/articles
curl -H "Authorization: Bearer dev-token" http://localhost:8000/api/v1/admin/insights
```

**Windows PowerShell**（`curl` 在 PowerShell 中是 `Invoke-WebRequest` 的别名，建议用 `Invoke-RestMethod` 或系统自带的 `curl.exe`）：

```powershell
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/api/v1/articles
Invoke-RestMethod -Headers @{ Authorization = "Bearer dev-token" } http://localhost:8000/api/v1/admin/insights
```

---

## 环境变量

后端配置统一使用 `APP_` 前缀（`backend/app/core/config.py`），可通过环境变量或 `backend/.env` 注入：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_APP_NAME` | `Blog Aggregator` | 应用名称（OpenAPI 标题） |
| `APP_ENVIRONMENT` | `development` | `test` 时跳过默认类别初始化（避免污染测试库） |
| `APP_API_V1_PREFIX` | `/api/v1` | 接口前缀 |
| `APP_DATABASE_URL` | `sqlite:///./data/app.db` | 数据库连接串；生产用 `postgresql+psycopg2://...` |
| `APP_REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串（预留） |
| `APP_ADMIN_TOKEN` | `change-me-in-production` | **维护者令牌，生产必须替换为强随机值** |
| `APP_ADMIN_ACTOR` | `admin` | 变更审计中记录的"谁" |
| `APP_CORS_ORIGINS` | `["http://localhost:5173","http://localhost:3000"]` | 允许的前端来源 |
| `APP_CRAWLER_USER_AGENT` | `BlogAggregatorBot/0.1 (...)` | 爬虫 UA，建议替换为可联系到你的信息 |
| `APP_CRAWLER_TIMEOUT_SECONDS` | `10.0` | 单次请求超时 |
| `APP_CRAWLER_MIN_INTERVAL_SECONDS` | `1.0` | 单站最小请求间隔（礼貌限速） |
| `APP_CRAWLER_MAX_PAGES_PER_RUN` | `20` | 单次调度单站最大抓取页数 |

容器编排相关变量见 `infra/.env.example`（`POSTGRES_*`、`APP_ADMIN_TOKEN`、`PIP_INDEX_URL` 等）。

---

## 接口一览

### 公开接口（匿名访问）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 健康探针 |
| `GET` | `/api/v1/articles` | 文章列表：`category`、`source_id`、`tag`、`date_from`、`date_to`、`page`、`page_size` |
| `GET` | `/api/v1/articles/{id}` | 文章详情：合并组全部来源、关联推荐、发布时间与采集时间 |
| `GET` | `/api/v1/categories` | 启用中的受控类别及文章数 |
| `GET` | `/api/v1/sources` | 来源维度新鲜度（最后成功更新时间 / 最后抓取时间） |

### 维护者接口（`Authorization: Bearer <APP_ADMIN_TOKEN>`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/admin/ping` | 令牌连通性检查 |
| `GET/POST` | `/api/v1/admin/sources` | 来源列表 / 新建（含主题、关键词、黑白名单、权重、频率） |
| `GET/PATCH` | `/api/v1/admin/sources/{id}` | 查看 / 编辑来源配置 |
| `GET` | `/api/v1/admin/sources/frequency-tiers` | 建议更新频率档位（高频/普通/低频） |
| `GET/POST` | `/api/v1/admin/categories` | 类别列表 / 新建 |
| `PATCH` | `/api/v1/admin/categories/{id}` | 类别改名 |
| `POST` | `/api/v1/admin/categories/{id}/merge` | 类别合并 |
| `POST` | `/api/v1/admin/categories/{id}/status` | 类别启用 / 停用 |
| `GET` | `/api/v1/admin/categories/{id}/history` | 类别变更历史 |
| `POST` | `/api/v1/admin/articles/{id}/category` | 文章重新归类 |
| `POST` | `/api/v1/admin/articles/{id}/inaccessible` | 标记原文不可访问并触发主记录切换 |
| `GET/PATCH` | `/api/v1/admin/dedup/settings` | 查看 / 调整近重复阈值（默认 0.90） |
| `GET` | `/api/v1/admin/dedup/history` | 阈值变更记录 |
| `POST` | `/api/v1/admin/dedup/rollback` | 回滚到指定变更记录 |
| `POST` | `/api/v1/admin/dedup/preview` | 阈值变更预览（将新增合并 / 拆分 / 新增关联） |
| `GET` | `/api/v1/admin/dedup/hits` | 去重命中记录（完全重复 / 近重复 / 关联，含依据与来源） |
| `GET` | `/api/v1/admin/dedup/groups` | 合并组主记录与全部成员 |
| `POST` | `/api/v1/admin/dedup/groups/refresh` | 重新应用主记录选择规则（检测失效并切换） |
| `POST` | `/api/v1/admin/dedup/groups/{key}/refresh` | 刷新指定合并组主记录 |
| `GET` | `/api/v1/admin/insights` | 分类分布 + 去重命中统计 |

所有错误响应统一为：

```json
{ "error": { "code": "NOT_FOUND", "message": "文章不存在", "details": null } }
```

---

## 网站使用说明

> 前端共三个页面：`/`（文章列表）、`/articles/:id`（文章详情）、`/admin`（维护者概览）。
> 列表与详情为匿名访问；维护者接口与 `/admin` 需要管理令牌。
>
> **操作系统差异说明**：第一、二节是浏览器操作，与系统无关，Windows / Linux / macOS 完全相同；
> 差异只出现在第三节及之后的**命令行与定时任务**上，因此这些小节按系统分别给出命令
> （支持范围见 [支持的系统](#支持的系统)）。

### 一、访客：浏览文章

| 步骤 | 操作 | 说明 |
| --- | --- | --- |
| 1 | 打开 `http://localhost:3000/`（或部署域名） | 进入文章列表，默认每页 10 条，按 `发布时间 → 采集时间` 倒序 |
| 2 | 点击分类标签 | 顶部"类别筛选"由 `/api/v1/categories` 动态生成，点击后回到第 1 页并按该类别过滤；点击"全部"取消筛选 |
| 3 | 翻页 | 列表底部"分页"控件提供"上一页 / 下一页"并显示"第 X / Y 页"，点击后重新请求对应页数据 |
| 4 | 阅读卡片信息 | 每张卡片包含：标题（可点击进详情）、摘要、类别、标签、**主来源**、`发布于` 与 `采集于` 两个时间、`共 N 个来源`（该文章存在合并时显示） |
| 5 | 查看来源新鲜度 | 列表页底部"**来源更新状态**"区块列出每个来源的名称与"最后更新"时间，用于判断数据是否在正常更新 |
| 6 | 进入详情 | 点击标题进入 `/articles/{id}` |

> 列表页当前提供"分类筛选 + 分页"控件；来源、标签、日期区间等筛选参数已由 `GET /api/v1/articles` 支持，
> 可直接通过 API / Swagger 使用，页面控件尚未提供。

**文章详情页包含：**

- 标题、类别、标签、正文；
- **原文发布时间** 与 **采集时间**（两者分别标注，便于判断内容新旧）；
- **来源（N）** 列表：合并组内的**全部来源**，每条含来源名、原文链接（新窗口打开）、该来源的发布时间与采集时间，主记录来源标注"主来源"；
- **关联推荐（当前由接口提供）**：详情接口会返回 `related_articles`（被判定为"同一事件不同视角"的文章），
  可通过 `GET /api/v1/articles/{id}` 或 Swagger UI 查看；前端页面尚未渲染该区块；
- 顶部"← 返回列表"。

> 提示：如果一篇文章曾被多个站点转载，列表只会显示一条（合并后的主记录），但详情页会给出所有转载来源的原文链接，这正是"合并但可追溯"的设计意图。

### 二、维护者：查看概览

1. 打开 `http://localhost:3000/admin`；
2. 在"**管理令牌**"输入框填入后端 `APP_ADMIN_TOKEN` 的值（默认 `change-me-in-production`，本地开发可用 `dev-token` 等）；
3. 点击"**加载概览**"，页面会请求 `GET /api/v1/admin/insights` 并展示：
   - **分类分布**：各受控类别下的可见文章数（含"未分类"）；
   - **去重命中统计**：完全重复 / 近重复 / 关联推荐 / 合并去重合计 / 文章总数 / 去重后独立文章；
4. 页面底部提供三个管理入口（来源配置 / 类别管理 / 去重策略管理）与"← 返回文章列表"。

> 令牌只保存在页面内存中，刷新后需重新填写；若提示"鉴权失败，请检查管理令牌"，说明令牌与后端配置不一致。
> 三个管理入口当前为占位页，对应的后端能力已实现，可直接通过 `http://localhost:8000/docs`（Swagger UI）或下述 curl 调用。

### 三、维护者：配置第一个来源并看到内容（端到端上手）

> 本节是命令行操作，因此按系统分别给出命令。为避免各系统引号/转义差异，
> 建议先把请求体保存为 UTF-8 编码的 `source.json`，再用文件方式提交。

**第 1 步：准备 `source.json`（三系统一致）**

```json
{
  "name": "示例技术博客",
  "site_url": "https://blog.example.com/",
  "list_type": "whitelist",
  "focus_area_name": "后端与 AI",
  "focus_area_description": "关注分布式系统与机器学习",
  "keywords": ["架构", "机器学习"],
  "example_urls": ["https://blog.example.com/posts/1"],
  "weight": 5.0,
  "update_frequency": "normal",
  "exclude_keywords": ["招聘", "广告"]
}
```

**第 2 步：调用接口新建来源**

Linux / macOS / Git Bash / WSL2：

```bash
export API=http://localhost:8000/api/v1
export TOKEN=dev-token                  # 与 APP_ADMIN_TOKEN 保持一致

# 1) 校验令牌可用
curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/ping"

# 2) 新建白名单来源（请求体来自 source.json）
curl -s -X POST "$API/admin/sources" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @source.json

# 3) 查看来源与建议频率档位
curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/sources"
curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/sources/frequency-tiers"
```

Windows PowerShell：

```powershell
$API = "http://localhost:8000/api/v1"
$TOKEN = "dev-token"
$headers = @{ Authorization = "Bearer $TOKEN" }

# 1) 校验令牌可用
Invoke-RestMethod -Uri "$API/admin/ping" -Headers $headers

# 2) 新建白名单来源（按字节读取并以 UTF-8 发送，避免中文乱码）
$body = [System.IO.File]::ReadAllBytes("source.json")
Invoke-RestMethod -Method Post -Uri "$API/admin/sources" -Headers $headers `
  -ContentType "application/json" -Body $body

# 3) 查看来源与建议频率档位
Invoke-RestMethod -Uri "$API/admin/sources" -Headers $headers
Invoke-RestMethod -Uri "$API/admin/sources/frequency-tiers" -Headers $headers
```

Windows cmd（使用系统自带 `curl.exe`，不要用 PowerShell 中的 `curl` 别名）：

```bat
curl.exe -s -X POST "http://localhost:8000/api/v1/admin/sources" ^
  -H "Authorization: Bearer dev-token" -H "Content-Type: application/json" ^
  --data-binary "@source.json"
```

**第 3 步：触发一次采集（三系统同一命令）**

调度入口目前是后端服务函数（尚未暴露 HTTP 接口）。进入 `backend` 目录并激活虚拟环境后执行：

```bash
python -c "from app.db.session import get_session_factory as f; from app.services import scheduler_service as s; db = f()(); print(s.run_scheduler_tick(db)); db.close()"
```

> - Windows PowerShell / cmd、Linux、macOS 均可直接使用这一条命令（PowerShell 中保持双引号即可）；
> - 该函数按"来源配置的频率是否到期"决定抓取对象，因此重复执行是安全的（幂等）。

**第 4 步**：回到浏览器刷新列表，即可看到采集到的文章。

### 四、维护者：周期性采集的定时任务（按系统）

调度器自身会按各来源的频率判断是否到期，因此定时任务的间隔是"**检查频率**"而非"抓取频率"，
建议 **每 30–60 分钟**触发一次即可。

**Linux（cron / systemd timer）**

```bash
crontab -e
```

```cron
*/30 * * * * cd /path/to/ai-blog-aggregator/backend && /path/to/ai-blog-aggregator/backend/.venv/bin/python -c "from app.db.session import get_session_factory as f; from app.services import scheduler_service as s; db = f()(); print(s.run_scheduler_tick(db)); db.close()" >> /var/log/aggregator-crawl.log 2>&1
```

如需更规范的服务管理，可改用 systemd timer（`OnUnitActiveSec=30min`）。

**macOS（cron 或 launchd）**

macOS 仍可使用与 Linux 相同的 `crontab -e`；更推荐用 launchd：
新建 `~/Library/LaunchAgents/com.example.aggregator-crawl.plist`，在 `ProgramArguments` 中填入
虚拟环境 Python 与上述 `-c` 脚本，并设置 `StartInterval` 为 `1800`，然后 `launchctl load` 该 plist。

**Windows（任务计划程序 / schtasks）**

1. 新建 `run_crawl.cmd`（把路径换成你的实际路径）：

```bat
@echo off
cd /d C:\path\to\ai-blog-aggregator\backend
rem 使用 PostgreSQL 时取消下一行注释并填入连接串
rem set APP_DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/blog
.venv\Scripts\python.exe -c "from app.db.session import get_session_factory as f; from app.services import scheduler_service as s; db = f()(); print(s.run_scheduler_tick(db)); db.close()"
```

2. 注册每 30 分钟执行一次的计划任务（PowerShell 或 cmd 均可）：

```powershell
schtasks /Create /SC MINUTE /MO 30 /TN "BlogAggregatorCrawl" /TR "C:\path\to\run_crawl.cmd"
```

3. 常用管理命令：立即执行一次 `schtasks /Run /TN "BlogAggregatorCrawl"`；删除 `schtasks /Delete /TN "BlogAggregatorCrawl" /F`。

> 容器部署时：可在宿主用 cron 调用 `docker compose -f infra/docker-compose.yml exec api python -c "…"`，
> 或增加一个只负责定时触发采集的 sidecar 容器。

### 五、维护者常见操作速查

| 我想…… | 去哪里做 |
| --- | --- |
| 排除某个站点 | `PATCH /api/v1/admin/sources/{id}`，把该来源设为 `list_type: "blacklist"`；黑名单来源不会被调度抓取 |
| 过滤某类内容（如招聘/广告） | 来源的 `exclude_keywords`，命中即标记为 `filtered`，不进入列表 |
| 调整来源重要性（影响合并主记录） | 来源的 `weight`，权重越高越容易被选为合并组主记录 |
| 调整采集频率 | 来源的 `update_frequency`（`high`/`normal`/`low`/`custom`）与 `custom` 时的 `update_interval_seconds` |
| 新增/改名/合并/停用类别 | `/admin/categories` 系列接口（合并会同步迁移文章与来源归属并记录历史） |
| 把未分类文章归入某类别 | `POST /admin/articles/{id}/category` |
| 处理原文已失效的文章 | `POST /admin/articles/{id}/inaccessible`，系统会自动切换合并组主记录 |
| 判断去重是否过激/过松 | `GET /admin/dedup/hits` 看判定依据；`POST /admin/dedup/preview` 预览阈值效果 |
| 调整近重复阈值 | `PATCH /admin/dedup/settings`（默认 0.90），历史可在 `/admin/dedup/history` 查看并 `POST /admin/dedup/rollback` 回滚 |
| 查看合并组构成 | `GET /admin/dedup/groups`，可用 `POST .../refresh` 重新评选主记录 |
| 查看整体效果 | `GET /admin/insights` 或前端 `/admin` 页面 |

---

## 核心规则说明

### 内容质量过滤（`app/filtering`）

按顺序判定，命中即标记为 `filtered`（保留原始记录用于审计，但所有面向用户的查询都会排除）：

0. **来源入口页**（URL 等于来源的 `site_url`，即站点首页/栏目页）—— 入口页只用于发现文章链接，不作为文章；
1. 正文过短（< 10 字符，疑似非文章页）；
2. 命中来源配置的**排除词**；
3. 标题含"首页/导航/目录/404"等占位特征且正文偏短；
4. 命中 ≥ 2 个广告/营销话术（立即购买、限时优惠、扫码关注…）；
5. 链接文本占比 ≥ 50%（纯导航/聚合页）。

### 分类与标签（`app/classifier`）

- 受控类别由维护者维护，初始预置 7 个默认类别；
- 关键词打分：**标题权重 3 / 正文权重 1**，取最高分类别；
- 无任何命中时落入"其他"并标记为**未分类**，维护者可一键重新归类。

### 去重与关联（`app/dedup`）

| 判定 | 方法 | 默认阈值 | 处理 |
| --- | --- | --- | --- |
| 完全重复 | 正文规范化（NFKC + 空白折叠）后的 SHA-256 指纹 | 精确相等 | 合并为同一合并组 |
| 近重复 | 64 位 SimHash，相似度 = `1 − 汉明距离 / 64` | **0.90**（可配置） | 合并为同一合并组 |
| 关联推荐 | 同上相似度，高于下限但不达合并阈值 | **0.50** | 不合并，仅互相推荐 |

- 阈值提高会让原本合并的文章**拆分**，降低会让更多文章**合并**；
- 每次调整都会写入变更历史（旧值/新值/操作者/时间），支持一键回滚；
- 调整前可先调用预览接口查看"将新增合并 / 将拆分 / 将新增关联"的清单；
- 同一对文章若被判定为合并，则原有的关联关系会被移除（合并优先级高于关联）。

### 主记录选择（`app/dedup/primary.py`）

合并组展示的主记录按以下优先级选出：

1. 来源权威权重（高者优先）
2. 发布时间最早
3. 内容完整度（正文更长者优先）
4. 原文可访问性

> 只要组内仍有**可访问**的来源，就只在可访问成员中评选，因此主记录原文失效时会自动切换到组内其他有效来源；
> 完全并列时按创建时间、再按 ID 兜底，保证结果稳定可复现。
> 详情页始终展示**全部来源**及其原文链接，而不仅展示主记录。

### 更新调度（`app/scheduler`）

| 档位 | 默认间隔 |
| --- | --- |
| 高频 | 3 小时 |
| 普通（未配置时的默认值） | 24 小时 |
| 低频 | 7 天 |
| 自定义 | 由来源的 `update_interval_seconds` 指定 |

调度器仅处理**启用中且非黑名单**的来源；重复触发依赖指纹/合并记录的幂等性，不会产生重复文章或重复关系。

---

## 数据模型

核心表（`backend/app/db/models.py`，迁移见 `backend/alembic/versions/`）：

| 表 | 作用 |
| --- | --- |
| `sources` | 来源/关注领域：站点、黑白名单、权重、频率、最后抓取与最后成功时间 |
| `categories` / `category_history` | 受控类别及其变更（新建/改名/合并/停用）审计 |
| `articles` | 文章：标题、正文、摘要、指纹、SimHash、类别、状态、发布时间、采集时间、可访问性 |
| `tags` / `article_tags` | 标签与文章多对多 |
| `duplicate_relations` | 合并组与关系：类型（完全重复/近重复/关联）、主记录标记、相似度、判定依据 |
| `crawl_pages` | 原始抓取页面，按 `(source_id, url)` 幂等 |
| `dedup_settings` / `dedup_setting_history` | 去重阈值当前值与变更/回滚历史 |

主键均为带前缀的字符串 ID（如 `article_…`、`source_…`），便于日志排查与跨环境迁移。

---

## 测试与质量门槛

**Windows / Linux / macOS 三系统命令一致**（需已激活后端虚拟环境）：

```bash
# 后端：格式 + 静态检查 + 测试（含覆盖率，CI 门槛 85%）
cd backend && black --check . && flake8 . && pytest

# 前端：静态检查 + 格式 + 类型检查/构建 + 单测
cd frontend && npm run lint && npm run format:check && npm run build && npm test
```

> 说明：`&&` 串联在 Linux / macOS / Git Bash / PowerShell 7 / cmd 中均可用；
> 若使用 **Windows PowerShell 5.1**（不支持 `&&`），请逐条执行：
> `cd backend`、`black --check .`、`flake8 .`、`pytest`。


当前状态：

- 后端 **207** 个测试全部通过，`app` 覆盖率 **≈95%**（`pytest --cov-fail-under=85`）；
- 前端 **19** 个测试全部通过，eslint / prettier / `tsc --noEmit` 均无告警；
- 爬虫与解析测试全部使用 `backend/tests/fixtures/*.html` 录制样本，**不访问真实网络**；
- `tests/test_e2e.py` 覆盖七类端到端场景：正常采集展示、完全重复合并、近重复合并、不同视角关联、
  未分类兜底与重新归类、主记录切换、阈值调整审计。

---

## CI

`.github/workflows/ci.yml` 在每次 push / PR 触发三个作业：

1. **Backend**：`black --check` → `flake8` → `pytest --cov-fail-under=85`；
2. **Frontend**：`eslint` → `prettier --check` → `tsc + vite build` → `vitest`；
3. **Infra**：`docker compose config -q` 校验编排文件。

> CI 运行在 `ubuntu-latest`（Linux），因此 **Linux 是被持续验证的平台**；
> Windows 由开发机人工验证，macOS 目前没有自动化验证（见[支持的系统](#支持的系统)）。

---

## 常见问题

**Q：为什么本地默认用 SQLite，容器里却是 PostgreSQL？**
A：本地/测试追求零依赖；生产用 PostgreSQL 以获得更好的并发与运维能力。业务代码通过 SQLAlchemy 2.0 统一抽象，
并对 SQLite/PostgreSQL 的差异做了处理（如 SimHash 以有符号 64 位存储、Alembic 开启 batch 模式）。

**Q：维护者接口返回 401？**
A：需要 `Authorization: Bearer <APP_ADMIN_TOKEN>`。默认令牌为 `change-me-in-production`，本地可通过环境变量覆盖；
前端 `/admin` 页面提供一个令牌输入框用于加载概览。

**Q：抓取到重复文章怎么办？**
A：先看 `/api/v1/admin/dedup/hits` 与 `/api/v1/admin/dedup/groups` 的判定依据；
若判定过激，可在 `/api/v1/admin/dedup/preview` 预览后调高阈值；若漏判严重则调低阈值，历史记录支持回滚。

**Q：`data/app.db` 或依赖目录被提交了吗？**
A：没有。`.gitignore` 已排除 `data/`、`*.db`、`node_modules/`、`dist/`、`__pycache__/`、`.env` 等本地产物。

**Q：项目支持哪些操作系统？macOS 能用吗？**
A：**Windows 10/11 与 Linux 为已验证的正式支持平台**（Windows 为本仓库开发环境，Linux 由 CI 每次验证）；
**macOS 预期可用但未经官方验证**；其他系统不支持。详见 [支持的系统](#支持的系统)。

**Q：Windows 上执行 `alembic upgrade head` 会因编码报错吗？**
A：不会。开发初期 `alembic.ini` 含中文注释，在 GBK 环境下 configparser 会抛 `UnicodeDecodeError`，
现已改为纯 ASCII，Windows 可直接执行迁移。

**Q：PowerShell 里 `curl` 报参数错误？**
A：PowerShell 5.1 的 `curl` 是 `Invoke-WebRequest` 的别名，不支持 `-H`/`--data-binary` 等参数。
请改用 `Invoke-RestMethod`（见[网站使用说明](#网站使用说明)）或系统自带的 `curl.exe`。

**Q：需要 WSL 才能用吗？**
A：不需要。Windows 上原生 PowerShell / cmd / Git Bash 均可运行；WSL2 也可，此时按 Linux 章节操作。

---

## AI 开发过程

本项目由**人机协作**完成：AI 负责编码、测试与文档产出，人类负责需求澄清、验收判定与偏差纠偏。
整体不是"一次性生成"，而是**逐票实现 → 跑测试 → 人工对照 → 收敛**的循环。

### 1. 方法论文档链

```
constitution.md（最高约束：可读性 / 模块化 / 测试分层 / 界面一致 / 性能 / 依赖锁定 / 访问控制）
      ↓ 约束
spec.md（需求规格与用户故事 1–9）
      ↓ 拆解
plan.md（技术方案与架构决策）
      ↓ 排序
tasks.md（任务与优先级）
      ↓ 细化为可验收单元
tickets.md（T01–T21：依赖顺序 + 验收标准 + 明确"不包含"的边界）
```

每张 ticket 同时给出"验收标准"和"不包含什么"，这使得"实现完成"有客观判据，也避免了范围蔓延
（例如 T20 只做概览，不重做 T04/T07/T15 的子管理功能）。

### 2. 单票工作循环

```mermaid
flowchart LR
    A[读 ticket<br/>验收标准 + 边界] --> B[设计模块/数据模型]
    B --> C[写实现 + 对应测试]
    C --> D[后端 pytest / black / flake8<br/>前端 vitest / lint / build]
    D -->|失败| C
    D -->|通过| E[汇报结果]
    E --> F{人工对照 spec/plan/tasks}
    F -->|发现偏差| C
    F -->|通过| G[进入下一票]
```

- **依赖先行**：严格按 `tickets.md` 的依赖顺序推进（如 T21 依赖 T10–T20），避免返工；
- **测试与实现同票交付**：每张票的测试文件与实现代码一起落地，例如 T16 新增 `test_filtering.py`、
  T18 新增 `test_primary_selection.py`、T21 新增 `test_e2e.py`；
- **可注入的边界**：网络（`Fetcher`）、数据库（`dependency_overrides`）、分类器（`Classifier`）均可替换，
  因此测试**从不访问真实网络**，全部使用 `tests/fixtures/*.html` 录制样本；
- **人工收敛替代自动化"converged"报告**：没有自动收敛检测脚本，由人在每票后对照文档指出出入并修正。

### 3. 迭代中真实修正的问题（节选）

| 现象 | 原因与修正 |
| --- | --- |
| `alembic.ini` 在 Windows 报 `UnicodeDecodeError (GBK)` | configparser 按本地编码读取，把中文注释改为 ASCII |
| `article_tags` 建表报错 | 关联表误用 `mapped_column`，改回 `Column(...)` |
| 校验异常处理抛 `TypeError` | `ValueError` 不可 JSON 序列化，用 `jsonable_encoder(exc.errors())` |
| 测试时间断言不稳定 | SQLite 回读为 naive datetime，新增 `assert_same_moment()` 统一按 UTC 比较 |
| 中文短正文解析失败 | 最小正文长度由 20 调到 10（中文短帖场景） |
| 默认类别顺序断言偶发失败 | Windows 时钟精度导致同秒排序不稳，改为断言集合相等 |
| T14 上线后 T09/T13 旧断言失败 | 关联关系是新增能力，放宽为"不允许合并类关系、允许关联关系" |
| 主记录重复处理有污染风险 | 在 `process_article` 中增加主记录/成员幂等守卫 |
| 阈值预览把"合并→关联"误归类 | 调整判定分支顺序：先判 `current == near` 的拆分，再判新增关联 |
| 主记录切换后旧主记录被丢出合并组 | 成员集合改为取"全部关系行"的 `article_id`，而非仅非主记录行 |
| "权重优先"与"主记录失效要能切换"冲突 | 只要组内存在可访问成员就**先限定候选集合**，再按权重等优先级评选 |
| 端到端列表多出一条文章 | 索引页正文过短被判为解析错误而进入列表，改为构造可被质量过滤拦下的导航页 |
| 真实抓取时 `crawl_pages` 报唯一约束冲突 | 定时任务重叠执行时"先查后插"存在竞态；改为把插入放进 SAVEPOINT，撞唯一约束则回滚并更新已有行 |
| 一个站点失败导致整轮调度中断 | `run_due_sources` 未隔离单来源异常；现改为回滚并把原因记录到 `PipelineReport.error`，其余来源继续 |
| 某博客所有文章标题都成了站名 | 该站 `<h1>` 写的是站名、文章标题在 `<title>` 的"站名: 标题"里；补充冒号分隔的标题提纯规则（不影响"标题 - 站名"写法） |
| 公开列表出现以 URL 为标题的条目 | 解析失败（error）记录与"无法解析的入口页"会漏进列表；改为入口页在解析前即判定，且公开列表排除 error |

### 4. 关键工程决策

- **保守去重**：以"误合并比漏合并更严重"为准则，用真实样本标定 SimHash 阈值——
  转载稿相似度 0.906、改写稿 0.625、无关 0.484，故近重复阈值取 **0.90**（转载合并、改写不合并），
  关联下限取 **0.50**；阈值可配置、可预览、可审计回滚，把判断权交回维护者。
- **合并优先于关联**：同一对文章被判为合并时，删除其原有的关联关系，避免语义重复。
- **可追溯而非删除**：被过滤/被合并的内容保留记录（`filtered`、合并组成员），仅在面向用户的查询中排除。
- **跨数据库一致**：SimHash 以有符号 64 位存储以兼容 PostgreSQL `BIGINT`；Alembic 开启 `render_as_batch`
  以支持 SQLite 的批式迁移；测试用内存库 + `StaticPool`。
- **ID 可读**：主键采用带前缀的字符串（`article_…`），便于日志排查与跨环境迁移。
- **可复现的"有内容"路径**：把 12 个热门技术博客做成种子脚本（`python -m app.scripts.seed_sources`）；
  候选站点逐条核对 `robots.txt` 与首页文章发现效果（403、TLS 异常、只能发现栏目页的站点被排除）。

### 5. 质量结果与分工

| 维度 | 结果 |
| --- | --- |
| 后端测试 | 207 个用例通过，`app` 覆盖率 ≈95%（CI 门槛 85%） |
| 前端测试 | 19 个用例通过，eslint / prettier / `tsc` 无告警 |
| 端到端 | `tests/test_e2e.py` 覆盖 7 类场景 + 用户故事核心路径 |
| CI | Backend / Frontend / Infra 三作业，push 与 PR 均自动执行 |

- **AI 承担**：按票实现、编写测试与 fixture、跨模块重构、文档与 README 生成、CI/容器编排配置；
- **人类承担**：需求与边界澄清、验收判定、优先级调整、指出实现与文档的出入、决定公开/私有等产品决策。

### 6. 已知局限与后续方向

- 采集触发目前是后端服务函数（`run_scheduler_tick` / `run_due_sources`），尚未提供 HTTP 手动触发接口；
- 前端管理子页面（来源/类别/去重策略）为占位页，能力通过后端接口与 Swagger UI 使用；
- 详情页尚未渲染"关联推荐"区块（`related_articles` 已由详情接口返回）；列表页也尚未提供来源/标签/日期筛选控件；
- 分类基于关键词规则，未引入模型；阈值标定样本量有限，需在真实数据上持续校准；
- 平台验证不完整：Windows（本机）与 Linux（CI）已验证，**macOS 未纳入 CI**，尚未实测；
- 可观测性（Prometheus/Grafana 指标、抓取成功率告警）与部署运维文档仍待补充。

---

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [`constitution.md`](constitution.md) | 项目治理原则（最高优先级，约束实现与评审） |
| [`spec.md`](spec.md) | 需求规格与用户故事 1–9 |
| [`plan.md`](plan.md) | 技术方案与架构决策 |
| [`tasks.md`](tasks.md) | 任务拆解与优先级 |
| [`tickets.md`](tickets.md) | **T01–T21** 逐票实现说明（依赖顺序、验收标准、边界） |
| [`docs/sharing-guide.md`](docs/sharing-guide.md) | **让其他人访问站点**：局域网 / 临时公网隧道 / 长期部署，含三系统命令与检查清单 |

---

## 抓取合规说明

- 抓取前检查目标站点 `robots.txt`，被拒绝的路径不会访问；
- 遵循单站最小请求间隔，避免对目标站点造成压力；
- 仅用于个人学习与研究用途的内容聚合；请在部署前确认目标站点的服务条款与版权要求，
  并自行承担合规责任。生产部署时请将 `APP_CRAWLER_USER_AGENT` 替换为可联系到运营者的标识。
