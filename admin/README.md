# 字库后台

管理员登录后上传原帖（页面图压缩包 + 全文释文），NAS 上的 worker 自动处理入库，生成预览；管理员看过预览、再输一次动态码批准后，自动上架 https://ziku.xlingdata.com/ 。

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

## 判定规则

`auto_ingest` 报告里：全局对齐对上率 ≥ 85%、缺字 < 5%、无失败页 → 「待审核」，可批准；否则「需人工」，转 agent 处理（行书粘连多、释文与帖不一致、剪裱乱序的帖常落在这一类）。
