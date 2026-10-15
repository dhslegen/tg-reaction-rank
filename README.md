# tg-reaction-rank

[中文](#中文) · [English](#english)

---

## 中文

把 Telegram 群里收到表情反应最多的消息排出来。自托管、单用户、Docker 一条命令部署。

- **两种数据来源**：用你自己的 Telegram 账号自动同步（不需要是管理员），或者上传 Telegram Desktop 导出的聊天记录。
- **榜单**：每个榜单就是一张表情权重表。内置「综合」按反应总数排名；你可以新建「最好笑（只算 😂）」「争议（👎 加分、👍 扣分）」之类的榜单。分数在查看时实时计算，改完权重立即生效。
- **筛选**：关键词搜索、近 7 天 / 30 天 / 今年 / 自定义时间、话题群按话题筛选，每条都能跳回原消息。
- **定期精华**：默认每周一 09:00 把各榜单前 10 名发到你的收藏夹（也可以改发到私人频道，或者关闭）。不会发回原群。
- **可恢复**：数据都在 `data/` 目录里，每天自动备份 SQLite 并保留 7 份；迁移服务器 = 复制 `data/` 和 `.env`。

### 快速开始

需要 Docker 和 Docker Compose，512MB 内存即可运行。

```bash
git clone https://github.com/dhslegen/tg-reaction-rank.git && cd tg-reaction-rank
cp .env.example .env
# 编辑 .env：至少填 ADMIN_PASSWORD 和 APP_SECRET（openssl rand -hex 32）
docker compose up -d --build
```

打开 `http://127.0.0.1:8000`，用 `ADMIN_PASSWORD` 登录。

- **只想看一次导出**：在「群」页上传 Telegram Desktop 导出的 `result.json`（导出时选「机器可读的 JSON」，不勾选媒体）。
- **自动同步**：在 [my.telegram.org](https://my.telegram.org) → API development tools 申请 `api_id` 和 `api_hash`，填进 `.env` 的 `TG_API_ID` / `TG_API_HASH`，然后执行 `docker compose up -d`。之后在网页「Telegram」页用手机号、验证码（以及两步验证密码）登录，再到「群」页添加要同步的群。

使用预构建镜像时，在 `.env` 里设置 `TGRANK_IMAGE=ghcr.io/dhslegen/tg-reaction-rank:latest`，然后执行 `docker compose pull && docker compose up -d`。

### 配置

部署期参数写在 `.env` 里，修改后需要 `docker compose up -d` 才会生效：

| 变量 | 说明 |
|---|---|
| `ADMIN_PASSWORD` | 网页管理员密码（必填） |
| `APP_SECRET` | ≥32 字符随机串，用于加密保存 Telegram 登录状态（必填） |
| `TG_API_ID` / `TG_API_HASH` | Telegram API 凭据；不填时只能使用导入功能 |
| `PORT` | 宿主机端口，默认 8000，只监听 127.0.0.1 |
| `TZ` | 时区，决定「近 7 天」的日界线和定时任务时间，例如 `Asia/Shanghai` |
| `TG_PROXY` | 可选，连接 Telegram 用的代理：`socks5://[用户:密码@]主机:端口` 或 `http://主机:端口` |
| `FORWARDED_ALLOW_IPS` | 可选，信任哪些反向代理的 `X-Forwarded-*` 头，见下文 |

同步节奏、刷新天数、推送时间与目标、榜单等运行期设置都在网页「设置」和「榜单」页修改，保存后立即生效。

默认同步节奏如下：

| 任务 | 默认节奏 | 做什么 |
|---|---|---|
| 拉取新消息 | 每 10 分钟 | 从上次同步到的消息之后继续拉取 |
| 刷新近期反应 | 每小时 | 重新拉取最近 7 天消息的反应、编辑和删除状态 |
| 全量校准 | 每周日 04:00 | 重扫全部历史，修正较早消息的编辑和删除 |
| 精华推送 | 每周一 09:00 | 推送上周一到本周一之间的各榜单前 10 名 |
| 数据库备份 | 每天 03:30 | 写入 `data/backups/`，保留最新 7 份 |

遇到 Telegram 限流（FloodWait）会自动等待后继续；网页「群」页每个群都有「立即同步」按钮。

### 反向代理与 HTTPS

服务本身只提供 HTTP，HTTPS 交给你已有的反向代理。服务默认只监听 `127.0.0.1:${PORT}`。

登录失败限流按客户端 IP 计算（同一 IP 15 分钟内失败 5 次锁 15 分钟），另有一层全局限流（15 分钟内共失败 30 次时全局锁 15 分钟）。在反向代理后面时，服务看到的来源 IP 都是代理的地址；要按真实 IP 限流，需要把代理地址填进 `FORWARDED_ALLOW_IPS`，服务才会采信代理传来的 `X-Forwarded-For`：

- **nginx / Caddy / 1Panel 与本服务在同一台机器上**，代理到 `127.0.0.1:8000`：请求经 Docker 端口转发进入容器，来源是 Docker 网桥网关。填 `FORWARDED_ALLOW_IPS=172.16.0.0/12`（自定义过 Docker 网段的话按实际填）。
- **反向代理也是容器、和本服务在同一个 Docker 网络**：填那个网络的网段，例如 `FORWARDED_ALLOW_IPS=172.18.0.0/16`（用 `docker network inspect` 查看）。
- **Cloudflare Tunnel（cloudflared）**：cloudflared 是实际连接本服务的代理。填 cloudflared 的来源地址，同机运行时与第一种情况相同；cloudflared 会带上 `X-Forwarded-For`。

不要填 `*`，除非服务端口只能被反向代理访问到。否则任何人都可以伪造 `X-Forwarded-For` 来绕过 IP 限流（全局限流仍然有效）。

被限流锁住时等 15 分钟即可；限流计数只保存在内存里，`docker compose restart app` 会立即清零。

### 备份、迁移与恢复

- 所有数据都在 `./data/`：`tgrank.db`（SQLite）和 `backups/`（每日快照，保留 7 份）。
- **迁移**：停掉旧服务，把 `data/` 和 `.env` 一起复制到新机器，再执行 `docker compose up -d`。**`.env` 里的 `APP_SECRET` 必须保持不变**，否则已保存的 Telegram 登录状态无法解密，需要重新登录（群和消息数据不受影响）。
- **从快照恢复**：`docker compose stop app`，用 `data/backups/` 里的某个快照覆盖 `data/tgrank.db`，同时删除旧的 `tgrank.db-wal` 和 `tgrank.db-shm`，再执行 `docker compose start app`。
- 异地备份不在本项目范围内，可以自行定期同步 `data/backups/`。

### 为什么只能跑一个实例

Telegram 不允许同一个登录状态（auth key）同时在两个地方连接，否则会以 `AUTH_KEY_DUPLICATED` 直接作废，需要重新登录。所以这里的「高可用」指的是可恢复，而不是多副本：单实例、单 worker、`restart: unless-stopped`、数据卷持久化、每日快照。不要给这个服务加副本，也不要把同一个 `data/` 同时挂到两台机器上。

### 命令行登录（备用）

网页向导不方便用时，可以在服务器上执行：

```bash
docker compose run --rm app login
docker compose restart app
```

命令行登录只在还没有有效登录状态时才会写入；已经登录时会拒绝，请先在网页「Telegram」页退出登录。

### 常见问题

- **网页提示「Telegram 登录已失效」**：可能是在手机的「设备」列表里移除了这个会话，或者同一个登录状态被两处同时使用。到「Telegram」页重新登录即可，同步会自动恢复。
- **换了 Telegram 账号**：登录后，新账号访问不到的群会被暂停同步，并注明原因；数据保留。
- **导入后没有任何反应数据**：旧版 Telegram Desktop 导出的文件不含反应信息，升级客户端后重新导出。
- **导入和同步的数据冲突**：以 API 同步的数据为准。导出文件通常是较旧的快照，不会覆盖已经同步过的消息。

### 开发

```bash
uv sync
uv run pytest
ADMIN_PASSWORD=dev APP_SECRET=$(openssl rand -hex 32) DATA_DIR=./data uv run python -m tgrank serve
```

技术栈：Python 3.12、FastAPI、Telethon、APScheduler、SQLite（WAL）；前端是原生 ES modules，没有构建步骤。Telegram 相关代码用 fake client 测试，不会真实登录。

镜像的基础是 Astral 官方发布在 GHCR 上的 `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`，在 `Dockerfile` 里用 digest 固定。升级方法：执行 `docker buildx imagetools inspect ghcr.io/astral-sh/uv:python3.12-bookworm-slim`，把输出顶部的多架构索引 `Digest` 替换到 `Dockerfile` 的 `ARG BASE` 里，然后重新构建并运行测试。

### 许可证

[MIT](LICENSE)。数字字体 Big Shoulders Display 以 SIL Open Font License 1.1 授权，见 `src/tgrank/static/fonts/OFL.txt`。

---

## English

Rank the messages in your Telegram groups by how many emoji reactions they received. Self-hosted, single user, one Docker Compose command. The web UI is in Chinese.

- **Two data sources**: sync automatically with your own Telegram account (you don't need to be an admin), or upload a Telegram Desktop chat export.
- **Boards**: a board is an emoji weight table. The built-in board counts every reaction as 1; create your own, such as "funniest (😂 only)" or "controversial (👎 adds, 👍 subtracts)". Scores are computed at query time, so weight changes apply immediately.
- **Filters**: keyword search, last 7 / 30 days, this year, or a custom range, filtering by topic in forum groups, and a link back to every original message.
- **Digest**: by default, every Monday at 09:00 the top 10 of each board is sent to your Saved Messages. You can send it to a private channel instead or turn it off. Nothing is ever posted back to the group.
- **Recoverable**: everything lives in `data/`. The SQLite database is backed up daily (7 snapshots kept). To migrate, copy `data/` and `.env`.

### Quick start

Requires Docker with Docker Compose; 512 MB of RAM is enough.

```bash
git clone https://github.com/dhslegen/tg-reaction-rank.git && cd tg-reaction-rank
cp .env.example .env
# edit .env: at least ADMIN_PASSWORD and APP_SECRET (openssl rand -hex 32)
docker compose up -d --build
```

Open `http://127.0.0.1:8000` and sign in with `ADMIN_PASSWORD`.

- **One-off export**: on the 群 (Groups) page, upload the `result.json` from a Telegram Desktop export (choose "Machine-readable JSON" and leave media unchecked).
- **Automatic sync**: get an `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org) → API development tools, put them in `.env` as `TG_API_ID` / `TG_API_HASH`, and run `docker compose up -d`. Then sign in on the Telegram page with your phone number, login code and, if enabled, your 2FA password. Finally, add the groups you want to sync on the Groups page.

To use a prebuilt image, set `TGRANK_IMAGE=ghcr.io/dhslegen/tg-reaction-rank:latest` in `.env`, then run `docker compose pull && docker compose up -d`.

### Configuration

Deployment settings live in `.env`. After changing them, run `docker compose up -d` to apply:

| Variable | Meaning |
|---|---|
| `ADMIN_PASSWORD` | Web UI password (required) |
| `APP_SECRET` | Random string of at least 32 characters, used to encrypt the stored Telegram session (required) |
| `TG_API_ID` / `TG_API_HASH` | Telegram API credentials; without them only the import feature works |
| `PORT` | Host port, default 8000, bound to 127.0.0.1 |
| `TZ` | Timezone used for day boundaries and schedules, e.g. `Asia/Shanghai` |
| `TG_PROXY` | Optional proxy for Telegram: `socks5://[user:pass@]host:port` or `http://host:port` |
| `FORWARDED_ALLOW_IPS` | Optional; which reverse proxies to trust for `X-Forwarded-*` headers (see below) |

Runtime settings (sync intervals, refresh window, digest schedule and target, boards) are edited in the web UI and take effect immediately.

Default schedule:

| Job | Default | What it does |
|---|---|---|
| Fetch new messages | every 10 min | Continues from the last synced message |
| Refresh recent reactions | hourly | Re-fetches reactions, edits and deletions for the last 7 days |
| Full calibration | Sundays 04:00 | Rescans the whole history to catch edits and deletions of older messages |
| Digest | Mondays 09:00 | Sends the top 10 of each board for the period from last Monday to this Monday |
| Database backup | daily 03:30 | Writes to `data/backups/` and keeps the newest 7 |

Telegram FloodWait limits are waited out automatically. Every group also has a "sync now" button on the Groups page.

### Reverse proxy and HTTPS

The app itself only serves plain HTTP; put your existing reverse proxy in front of it for HTTPS. By default it listens only on `127.0.0.1:${PORT}`.

Failed logins are rate-limited per client IP: 5 failures within 15 minutes lock that IP for 15 minutes. A second, global limit locks all logins for 15 minutes after 30 failures within 15 minutes. Behind a proxy, every request appears to come from the proxy. To rate-limit by the real client IP, list the proxy's address in `FORWARDED_ALLOW_IPS` so that its `X-Forwarded-For` header is trusted:

- **nginx / Caddy / 1Panel on the same host**, proxying to `127.0.0.1:8000`: requests reach the container through Docker's port forwarding and arrive from the bridge gateway. Use `FORWARDED_ALLOW_IPS=172.16.0.0/12`, or your custom Docker address pool.
- **Proxy running as a container on the same Docker network**: use that network's subnet, e.g. `172.18.0.0/16` (check with `docker network inspect`).
- **Cloudflare Tunnel**: cloudflared is the proxy that connects to the app, so trust its source address. On the same host this is the same as the first case. cloudflared sends `X-Forwarded-For`.

Avoid `*` unless the port is reachable only by your proxy. Otherwise anyone can forge `X-Forwarded-For` to dodge the per-IP limit (the global limit still applies).

If you get locked out, wait 15 minutes. Counters are kept in memory only, so `docker compose restart app` clears them immediately.

### Backup, migration, restore

- All state is in `./data/`: `tgrank.db` (SQLite) and `backups/` (daily snapshots, newest 7 kept).
- **Migrate**: stop the old instance, copy `data/` **and** `.env` to the new host, then run `docker compose up -d`. Keep `APP_SECRET` unchanged. If it changes, the stored Telegram session can't be decrypted and you'll need to sign in again; group and message data are unaffected.
- **Restore a snapshot**: run `docker compose stop app`, replace `data/tgrank.db` with a file from `data/backups/`, delete any `tgrank.db-wal` / `tgrank.db-shm`, then run `docker compose start app`.
- Off-site backup is out of scope; sync `data/backups/` yourself if you need it.

### Why exactly one instance

Telegram revokes a session that is used from two places at once (`AUTH_KEY_DUPLICATED`). "High availability" here therefore means recoverability, not replicas: one instance, one worker, `restart: unless-stopped`, a persistent volume and daily snapshots. Never scale this service out or mount the same `data/` on two machines.

### CLI login (fallback)

```bash
docker compose run --rm app login
docker compose restart app
```

The CLI only writes a session when no valid one exists. If you are already signed in, sign out on the Telegram page first.

### Development

```bash
uv sync
uv run pytest
ADMIN_PASSWORD=dev APP_SECRET=$(openssl rand -hex 32) DATA_DIR=./data uv run python -m tgrank serve
```

Stack: Python 3.12, FastAPI, Telethon, APScheduler, SQLite (WAL). The frontend uses native ES modules with no build step. Telegram code is tested against a fake client; tests never sign in to a real account.

The image is based on Astral's official `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` from GHCR, pinned by digest in the `Dockerfile`. To upgrade, run `docker buildx imagetools inspect ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, copy the multi-arch index `Digest` printed at the top into `ARG BASE`, then rebuild and run the tests.

### License

[MIT](LICENSE). The Big Shoulders Display font is licensed under the SIL Open Font License 1.1; see `src/tgrank/static/fonts/OFL.txt`.
