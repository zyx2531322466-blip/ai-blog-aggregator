# 让其他人访问你的站点

> 本篇是「如何把本站分享给别人」的独立操作手册，覆盖 **Windows / Linux / macOS** 三种系统。
> 支持范围与前置要求见 [README 的支持的系统](../README.md#支持的系统)。
>
> 一句话结论：
> **同一局域网**用「内网 IP + 3000 端口」（零成本、最稳）；**发给外部的人**用 cloudflared 临时公网隧道（免费、无需注册、不需要公网 IP 与防火墙设置）。

---

## 0. 三种分享方式怎么选

| 方式 | 谁能访问 | 成本 | 稳定性 | 适用场景 |
| --- | --- | --- | --- | --- |
| **A. 局域网** | 同一 Wi-Fi / 公司内网的设备 | 免费 | 高，不依赖第三方 | 同事、家人在同一网络 |
| **B. 临时公网隧道**（cloudflared Quick Tunnel） | 任何有网的人 | 免费、无需注册 | 依赖你自己的电脑开着，地址每次重启都变 | 演示、评审、发给外部的人看 |
| **C. 长期公网部署** | 任何有网的人 | 需云服务器（约 ¥30–60/月） | 高，24 小时在线 | 正式对外、需要固定网址 |

下面分别给出完整步骤。推荐顺序：**先 A 验证服务本身没问题 → 再 B 发给外部的人**。

---

## 1. 分享前的准备（三种方式都要做）

### 1.1 启动服务

**Windows（PowerShell）/ Linux / macOS 通用：**

```bash
cd /path/to/ai-blog-aggregator
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps
```

确认三个服务 `api` / `web` 为 `Up`（`db`、`redis` 应为 `healthy`）。容器方式会把 `3000`（前端）和 `8000`（API）绑定到 `0.0.0.0`，**局域网可直接访问**，无需改配置。

### 1.2 检查站点里有没有内容

别人打开一个空站点会以为坏了。先确认有文章：

```bash
# Linux / macOS / Windows Git Bash
curl -s "http://localhost:8000/api/v1/articles?page_size=1"
```

```powershell
# Windows PowerShell
Invoke-RestMethod "http://localhost:8000/api/v1/articles?page_size=1" | Select-Object total
```

`total` 为 0 时，先写入热门博客来源并抓取：

```bash
# 1) 写入 12 个热门技术博客（幂等，已存在的会跳过）
docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed_sources

# 2) 触发一次采集（限制每站 5 页，遵守 robots.txt 与 1 秒限速）
docker compose -f infra/docker-compose.yml exec -T \
  -e APP_CRAWLER_MAX_PAGES_PER_RUN=5 -e APP_CRAWLER_TIMEOUT_SECONDS=20 \
  api python -c "from app.db.session import get_session_factory as f; from app.services import scheduler_service as s; db=f()(); print(len(s.run_scheduler_tick(db))); db.close()"
```

> 采集需要几分钟。也可以只加你自己关心的来源（`POST /api/v1/admin/sources`，字段见 [README 接口一览](../README.md#接口一览)）。

### 1.3 换成强令牌（**对外分享前必须做**）

`APP_ADMIN_TOKEN` 是维护者后台（`/admin` 页与 `/admin/*` 接口）的唯一凭据。默认值与弱口令必须替换：

```bash
# 生成强随机令牌（三系统同一命令）
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

把结果写进 `infra/.env` 的 `APP_ADMIN_TOKEN=`，然后重建 api 容器生效：

```bash
docker compose -f infra/docker-compose.yml up -d --force-recreate api
```

> ⚠️ **只写 `infra/.env`**（已被 `.gitignore` 忽略）。不要写进 `infra/.env.example`，那是个被 git 跟踪的文件，提交后令牌会公开。
> 也不要把令牌和公网链接一起发给别人——`/admin` 页面需要令牌才能加载数据。

### 1.4 顺手降低本机暴露面（可选但建议）

`infra/docker-compose.yml` 默认把 PostgreSQL(5432) 与 Redis(6379) 也发布到所有网卡，而示例密码是 `blog`。局域网环境下建议只绑本机：

```yaml
    ports:
      - "127.0.0.1:5432:5432"    # db
      - "127.0.0.1:6379:6379"    # redis
```

改完执行 `docker compose -f infra/docker-compose.yml up -d` 生效。这样只有 `3000`（和可选的 `8000`）对外。

---

## 2. 方式 A：同一局域网访问

### 2.1 找到本机内网 IP

**Windows（PowerShell）：**

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.PrefixOrigin -in 'Dhcp','Manual' -and $_.IPAddress -notlike '169.*' } |
  Select-Object IPAddress, InterfaceAlias
```

**Linux：**

```bash
hostname -I        # 或 ip -4 addr show scope global
```

**macOS：**

```bash
ipconfig getifaddr en0     # Wi-Fi；有线网口可能是 en1
```

假设得到 `192.168.1.23`。

### 2.2 让别人打开

| 启动方式 | 别人访问的地址 |
| --- | --- |
| Docker Compose（`web` 容器） | `http://192.168.1.23:3000` |
| 后端本地开发（`uvicorn`） | `http://192.168.1.23:5173`（前端 Vite 已 `host: true`） |

> 前端通过同源代理访问 `/api`，所以**不需要改 CORS 配置**。

### 2.3 如果本地开发（非容器），后端要监听所有网卡

`uvicorn` 默认只监听 `127.0.0.1`，别人访问不到。启动时加 `--host 0.0.0.0`：

```bash
# Linux / macOS / Windows Git Bash
cd backend
APP_ADMIN_TOKEN=dev-token python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```powershell
# Windows PowerShell
cd backend
$env:APP_ADMIN_TOKEN = "dev-token"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2.4 放行防火墙（Windows 首次可能弹窗）

容器方式由 Docker Desktop 代管端口，通常无需额外配置。若别人仍连不上：

```powershell
# Windows：只放行专用网络的 3000 端口
New-NetFirewallRule -DisplayName "Blog Aggregator 3000" -Direction Inbound `
  -Protocol TCP -LocalPort 3000 -Action Allow -Profile Private
```

```bash
# Linux（ufw 示例）
sudo ufw allow from 192.168.1.0/24 to any port 3000 proto tcp
```

> 排障：在自己电脑上 `http://localhost:3000` 能开、别人打不开 → 99% 是防火墙或不在同一网段。

---

## 3. 方式 B：临时公网链接（推荐给外部的人）

使用 **cloudflared Quick Tunnel**：免费、无需注册、不需要公网 IP，也**不需要开放任何入站端口**（隧道是本机主动连出去）。

### 3.1 安装 cloudflared

**Windows（PowerShell，winget）：**

```powershell
winget install --id Cloudflare.cloudflared
# 装完关闭并重新打开 PowerShell，让 PATH 生效
cloudflared --version
```

**macOS（Homebrew）：**

```bash
brew install cloudflared
```

**Linux：**

```bash
# Debian / Ubuntu
curl -L -o cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
# 或直接用二进制
sudo curl -L -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
sudo chmod +x /usr/local/bin/cloudflared
```

> 网络受限装不上时，可下载 `cloudflared-windows-amd64.exe`（Windows）/ `cloudflared-darwin-amd64.tgz`（macOS）等发行包直接运行。

### 3.2 开隧道（三系统命令一致）

**先确认本机 `http://localhost:3000` 能正常打开**，再执行：

```bash
cloudflared tunnel --url http://localhost:3000
```

控制台会输出类似内容：

```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at:                                          |
|  https://random-words-1234.trycloudflare.com                                               |
+--------------------------------------------------------------------------------------------+
```

**把这个 `https://…trycloudflare.com` 链接发给别人即可**（自带 HTTPS）。该终端窗口必须保持运行。

### 3.3 为什么指向 3000 而不是 5173

- `3000` 是容器里的 nginx：既提供前端页面，又把 `/api` 反向代理到后端，**同源、无 CORS 问题**，且不校验 Host 头；
- `5173` 是 Vite 开发服务器（本项目安装的是 **5.4.21**），它带 Host 头校验，直接用隧道域名访问会返回
  `Blocked request. This host is not allowed.`。若确实要用 5173，需要在 `frontend/vite.config.ts` 的 `server` 中加
  `allowedHosts: ['.trycloudflare.com']` 并重启 dev server。

### 3.4 必须知道的限制

| 事项 | 说明 |
| --- | --- |
| 地址不固定 | 每次重启隧道都会生成新地址，旧链接立即失效 |
| 依赖你的电脑 | 电脑关机/睡眠、或关掉隧道窗口，别人立刻打不开（可 `powercfg /change standby-timeout-ac 0` 阻止 Windows 睡眠） |
| 无可用性保证 | Quick Tunnel 无 SLA，偶发 502 |
| 流量经过第三方 | TLS 在 Cloudflare 终止，不要放隐私/敏感数据 |
| 公开可读 | 任何拿到链接的人都能看公开接口与 `/docs`；维护者接口仍需令牌 |

### 3.5 备选隧道工具

| 工具 | 命令 | 说明 |
| --- | --- | --- |
| ngrok | `ngrok http 3000` | 需要注册并配置 authtoken，免费版地址随机 |
| localtunnel | `npx localtunnel --port 3000` | 无需注册，但**访客需输入你的公网 IP 作为密码**，体验较差 |
| Cloudflare Named Tunnel | `cloudflared tunnel run <名字>` | 需要 Cloudflare 账号与域名，可得到**固定**地址（见方式 C） |

---

## 4. 方式 C：长期公网部署（简述）

适合已经有云服务器的情况，核心是「一台机器 + 反向代理 + HTTPS」：

1. **云服务器**（1C2G 起）安装 Docker 与 compose 插件，拉取本仓库；
2. 复制 `infra/.env.example` 为 `infra/.env`，设置**强令牌**、正式数据库密码，并**移除或仅绑本机的 5432/6379 端口映射**；
3. `docker compose -f infra/docker-compose.yml up -d --build`；
4. 用 **Caddy**（自动申请证书，最省事）或 Nginx + certbot 做反向代理到 `127.0.0.1:3000`；
   也可以继续用 cloudflared 的 **Named Tunnel** 绑定自己的域名，免去开放 80/443 与证书管理；
5. 用 cron / systemd timer / 任务计划程序定时触发采集（见 [README 的定时任务小节](../README.md#四维护者周期性采集的定时任务按系统)）。

**上线前务必确认**：`APP_ADMIN_TOKEN` 已换强值、`/docs` 是否需要关闭或加保护、数据库端口未暴露、`APP_CRAWLER_USER_AGENT` 已填可联系到你的标识。

---

## 5. 分享检查清单（逐条确认）

- [ ] `docker compose ps` 中 `api` / `web` 均为 Up
- [ ] `GET /api/v1/articles` 返回 `total > 0`（站点不是空的）
- [ ] 本机 `http://localhost:3000` 能正常浏览列表与详情
- [ ] `APP_ADMIN_TOKEN` 已换成 `secrets.token_urlsafe(32)` 生成的强令牌，且只写在 `infra/.env`
- [ ] `infra/.env.example` 中没有真实令牌（`git diff -- infra/.env.example` 应无输出）
- [ ] `APP_CRAWLER_USER_AGENT` 已填可联系到你的标识
- [ ] （局域网）已放行防火墙；确认对方与你在同一网段
- [ ] （公网）不要连同令牌一起发送链接；演示结束及时关掉隧道

---

## 6. 常见故障排查

| 现象 | 原因与处理 |
| --- | --- |
| `localhost:3000` 拒绝连接 | 3000 只在容器方案下存在：先 `docker compose up -d`；本地开发请访问 5173 |
| 别人打不开、你自己能开（局域网） | 防火墙未放行，或不在同一网段；本地开发时后端是否加了 `--host 0.0.0.0` |
| 隧道链接 502 / 不能连接 | 本机 3000 没在跑，或容器刚重启还没就绪；先在浏览器确认 `localhost:3000` 正常 |
| 隧道链接打开是 `Blocked request` | 你把隧道指向了 5173（Vite Host 校验）；改指 3000，或配置 `allowedHosts` |
| 页面能开但列表为空 | 还没采集：执行 `seed_sources` + `run_scheduler_tick`（见 1.2） |
| 列表里出现"关于/栏目"页 | 已内置规则：来源入口页与导航页会被过滤；若仍出现，可在来源的 `exclude_keywords` 里补充 |
| 采集一直 `failed`、HTTP 500 | 目标站点（或其 CDN）间歇性故障，与本项目无关；稍后重跑，失败页会按 `(source_id, url)` 幂等重抓 |
| 改了令牌没生效 | 需要 `docker compose up -d --force-recreate api` 重建容器 |
| 端口被占用 | 改 `infra/docker-compose.yml` 的左侧端口（如 `3001:80`），或释放占用端口的进程 |

---

## 7. 演示结束后的收尾

```bash
# 关掉隧道：在 cloudflared 窗口按 Ctrl+C

cd /path/to/ai-blog-aggregator
docker compose -f infra/docker-compose.yml stop        # 暂停（保留数据）
docker compose -f infra/docker-compose.yml down        # 停止并删除容器（数据卷保留）
docker compose -f infra/docker-compose.yml down -v     # 连数据库数据一起清空（谨慎）
```
