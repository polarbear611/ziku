# 字库后台

管理员登录后上传原帖（页面图压缩包 + 全文释文），NAS 上的 worker 自动处理入库，生成预览；管理员看过预览、再输一次动态码批准后，自动上架 https://ziku.xlingdata.com/ 。

## 技术选型

| 部件 | 选型 | 理由 |
|---|---|---|
| 网页 | Flask 3 + gunicorn，服务端渲染，页面不带脚本 | 只有 4 个页面；CSP 直接禁脚本 |
| 账号/会话/任务/审计 | SQLite 单文件（0600） | 一两个管理员，用不到数据库服务 |
| 口令 / 第二因素 | scrypt（标准库）/ TOTP（RFC 6238） | 不加第三方依赖；验证器 App 离线可用 |
| 处理 | 现有 v2 流水线 + `v2/auto_ingest.py` | 与人工入库同一套代码 |
| 对齐打分模型 | PP-OCRv4 识别（RapidOCR，约 10MB，CPU） | NAS 无显卡；模型只打分，不定边界 |
| 估字高字体 | Noto Serif CJK TC（`ZIKU_FONT`/`ZIKU_FONT_INDEX`） | NAS 不能用 macOS 宋体 |
| 运行 | Docker Compose（web / worker / tunnel 共用一个镜像） | 限内存、限 CPU，不影响 NAS 上的 OpenClaw |
| 外网入口 | NAS 反向 SSH 隧道 → platform socat 桥 → nginx | 沿用教材站已验证的接法 |
| 上架 | rsync + platform 闸门脚本 | 只传一部帖；钥匙只能收货和 promote |

## 组成

| 部分 | 在哪 | 做什么 | 持有的凭据 |
|---|---|---|---|
| `app.py`（web 容器） | NAS，只绑 127.0.0.1:8790 | 登录、上传、看报告和预览、批准 | 无（只读写 `data/`） |
| `worker.py`（worker 容器） | NAS | 每 2 分钟扫 `data/inbox/`：安全解包 → `v2/auto_ingest.py` → 预览站；批准后合并 db.js → `deploy.sh` 上架 | 发布钥匙 `keys/deploy` |
| tunnel 容器 | NAS | autossh `-R 127.0.0.1:18790` 到 platform | 隧道钥匙 `keys/tunnel` |
| `platform/ziku-gate.sh` + `promote.py` | platform `~/ziku-admin/` | 发布钥匙的强制命令：只许 rsync 进 `incoming/<任务号>/`、`promote <任务号>`；校验后只替换一部帖和 db.js，先备份 | — |
| nginx `ziku-admin.xlingdata.com` | platform | 限流（登录 6 次/分钟/IP）、限包体 500MB、不让收录 | — |

## 登录与安全

- 口令（≥14 位，scrypt）+ TOTP（验证器 App），两样都要；同一个动态码不能用第二次。
- 网页上不能注册、不能找回口令；账号只能在 NAS 上用 `manage.py` 管。
- 连错 5 次锁 15 分钟，再锁时长翻倍；同一 IP 10 分钟最多失败 10 次。错误提示不区分哪一项错。
- 会话存服务端（库里只存凭证的哈希）；Cookie `__Host-`、Secure、HttpOnly、SameSite=Strict；30 分钟无操作或 8 小时到期；可「退出全部设备」。
- 所有提交校验 CSRF 令牌 + `Sec-Fetch-Site`；「批准发布」要再输动态码。
- 上传按文件头判 zip/rar；解包拒绝绝对路径、`..`、链接、设备文件，限 500 个文件、解压后 2GB；每张图用 Pillow 打开后重编码成 PNG，原文件名丢弃。
- 审计：登录成败、上传、批准、worker 状态变化都记 `audit` 表（`manage.py audit`）。

## 部署（NAS）

```bash
cd /home/op/ziku-admin            # admin/ 与 v2/ 代码放这里，compose.yml 拷到这一层
docker compose up -d --build
docker compose exec web python manage.py add <用户名>    # 输口令两次，扫屏幕上的二维码绑定验证器
```

platform 侧一次性开通：在本机运行 `bash admin/platform/setup-platform.sh`（写生产：受限公钥、闸门脚本、socat 桥、nginx server 块；均先备份）。DNS 加 `ziku-admin.xlingdata.com` → 123.56.245.17。

## 主要流程

1. 上传：存进 `data/inbox/<任务号>/`，状态「排队中」。
2. worker 每 2 分钟认领一部，挪到 `jobs/`，安全解包、图片重编码。
3. `auto_ingest.py`：定参数（底色中位数 < 110 判拓本；按列距缩放到约 170px）→ 预处理 → `seed_text` 全书全局对齐分页分列 → 整页对齐 → 墨块归属抠图 → potrace 矢量化 → 几何异常剔除。
4. 生成只含这部帖的预览站，判「待审核」或「需人工」。
5. 管理员看预览、再输动态码批准（网页只写一条批准记录）。
6. worker 取线上 `db.js` 合并新帖 → `deploy.sh`：rsync 到 platform `incoming/` → `promote` 校验、备份、原子替换 → 回读 db.js md5、字图 200、对照路径 404。

## 管理员使用手册

- 上传：代号用小写拼音加连字符（同代号再传会覆盖）；书体决定集字归库；**释文必须与帖上一致**，从第一页第一字开始，含题名落款；压缩包里图按文件名排序即页序。
- 等 2–25 分钟（视页数）刷新任务页；「待审核」→ 打开预览抽查字图与标字 → 输动态码批准 → 几分钟后「已上线」。
- 「需人工」：多为行书粘连、释文与帖不符、剪裱乱序，把任务号交给 agent，不要批准。
- 登录被锁：等 15 分钟或 `manage.py unlock`；换手机：`manage.py reset-totp`；怀疑被盗：「退出全部设备」+ `reset-pw` + `reset-totp`，`manage.py audit` 查记录。
- 每次上架前的线上状态备份在 platform `~/ziku-admin/backups/`。

## 判定规则

`auto_ingest` 报告里：全局对齐对上率 ≥ 85%、缺字 < 5%、无失败页 → 「待审核」，可批准；否则「需人工」，转 agent 处理（行书粘连多、释文与帖不一致、剪裱乱序的帖常落在这一类）。
