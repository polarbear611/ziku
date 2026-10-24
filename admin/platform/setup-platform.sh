#!/bin/bash
# 第 2 步：在 platform（生产，123.56.245.17）上为字库后台开通入口。在本机运行：bash admin/platform/setup-platform.sh
# 做的事（每项先备份，可回滚）：
#   1. ~/ziku-admin/：上架闸门 ziku-gate.sh + promote.py，incoming/ backups/ 目录
#   2. authorized_keys 追加两把受限公钥（来自 NAS 上生成的 keys/*.pub）：
#        隧道钥匙：restrict + 只许 -R 127.0.0.1:18790，不能登录、不能执行命令
#        发布钥匙：restrict + 强制命令 ziku-gate.sh（只能收货到 incoming/<任务号>/ 和 promote）
#   3. ~/ziku-admin/bridge.sh：socat 把 127.0.0.1:18790 桥到 docker 网关 172.21.0.1:18790（照抄 ctb-bridge.sh）
#   4. web2.conf 追加 ziku-admin.xlingdata.com server 块 -> nginx -t 通过才 reload，不通过自动还原
set -euo pipefail
cd "$(dirname "$0")"
P=platform
TS=$(date +%Y%m%d-%H%M%S)
[ "$(ssh $P cat /etc/machine-id)" = 20ee080d35104cbc9cf5d4799d8e3f7d ] || { echo "不是 platform，停止"; exit 1; }

echo "== 1. 闸门脚本"
ssh $P 'mkdir -p ~/ziku-admin/incoming ~/ziku-admin/backups && chmod 700 ~/ziku-admin'
ssh $P 'cat > ~/ziku-admin/ziku-gate.sh && chmod 700 ~/ziku-admin/ziku-gate.sh' < ziku-gate.sh
ssh $P 'cat > ~/ziku-admin/promote.py && chmod 600 ~/ziku-admin/promote.py' < promote.py
ssh $P 'cd ~/ziku-admin && bash -n ziku-gate.sh && python3 -m py_compile promote.py && md5sum ziku-gate.sh promote.py'
md5 -r ziku-gate.sh promote.py

echo "== 2. 受限公钥"
TUN=$(ssh nas cat /home/op/ziku-admin/keys/tunnel.pub)
DEP=$(ssh nas cat /home/op/ziku-admin/keys/deploy.pub)
ssh $P "cp -p ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak-$TS
grep -q 'ziku-admin-tunnel@nas' ~/.ssh/authorized_keys || echo 'restrict,port-forwarding,permitlisten=\"127.0.0.1:18790\",command=\"/bin/false\" $TUN' >> ~/.ssh/authorized_keys
grep -q 'ziku-admin-deploy@nas' ~/.ssh/authorized_keys || echo 'restrict,command=\"/home/op/ziku-admin/ziku-gate.sh\" $DEP' >> ~/.ssh/authorized_keys
grep -c 'ziku-admin-' ~/.ssh/authorized_keys"

echo "== 3. socat 桥"
ssh $P "sed -e 's/18081/18790/g' -e 's#/home/op/ctb-bridge#/home/op/ziku-admin/bridge#g' -e 's/textbook 上游桥/字库后台上游桥/' ~/ctb-bridge.sh > ~/ziku-admin/bridge.sh && chmod 700 ~/ziku-admin/bridge.sh && grep -n '18790\|PID=\|LOG=' ~/ziku-admin/bridge.sh"
ssh $P '~/ziku-admin/bridge.sh start'

echo "== 4. nginx"
C=/home/op/platform-docker/web/conf/web2.conf
ssh $P "cp -p $C $C.bak-$TS-ziku-admin"
ssh $P "grep -q 'ziku-admin.xlingdata.com' $C || cat >> $C" <<'NGX'

# ==== 字库后台 ziku-admin.xlingdata.com（2026-10-24）====
# 上游在家里 NAS 的 docker（/home/op/ziku-admin，web 容器 :8790），NAS 的 tunnel 容器 autossh -R 到本机 127.0.0.1:18790，
# 宿主 /home/op/ziku-admin/bridge.sh（socat）桥到 172.21.0.1:18790。应用自己做登录（口令 + TOTP），这里只限流和限包体。
# 链路自检：平台 ~/ziku-admin/bridge.sh status；NAS  cd ~/ziku-admin && docker compose ps
upstream ziku_admin { server 172.21.0.1:18790; }
limit_req_zone $binary_remote_addr zone=zkalogin:10m rate=6r/m;
limit_req_zone $binary_remote_addr zone=zkaall:10m rate=180r/m;
server {
    listen 443 ssl;
    server_name ziku-admin.xlingdata.com;
    ssl_certificate     /etc/nginx/cert/platform.xlingdata.com.pem;
    ssl_certificate_key /etc/nginx/cert/platform.xlingdata.com.key;
    client_max_body_size 500m;
    add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    location = /robots.txt { add_header Content-Type text/plain; return 200 "User-agent: *\nDisallow: /\n"; }
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 600s;
    proxy_request_buffering off;
    location = /login { limit_req zone=zkalogin burst=6 nodelay; proxy_pass http://ziku_admin; }
    location /        { limit_req zone=zkaall burst=120 nodelay; proxy_pass http://ziku_admin; }
}
NGX
if ssh $P 'docker exec twin-platform-nginx nginx -t' ; then
  ssh $P 'docker exec twin-platform-nginx nginx -s reload' && echo "nginx 已 reload"
else
  echo "nginx -t 失败，还原"; ssh $P "cp -p $C.bak-$TS-ziku-admin $C"; exit 1
fi
echo "== 完成。备份：authorized_keys.bak-$TS、web2.conf.bak-$TS-ziku-admin"
