#!/bin/bash
# worker 调用：deploy.sh <发布包目录 release/<任务号>> <帖目录名>
# 发布密钥在 platform 上被 ziku-gate.sh 锁死：只能 rsync 进 incoming/<任务号>/ 和 promote <任务号>
set -euo pipefail
REL=$1; BOOK=$2; JID=$(basename "$REL")
SSH="ssh -i /keys/deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/keys/known_hosts -o StrictHostKeyChecking=yes -o BatchMode=yes"
HOST=op@123.56.245.17
rsync -rt --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r -e "$SSH" "$REL/" "$HOST:incoming/$JID/"
$SSH $HOST "promote $JID"
# 回读：线上 db.js 与发布包逐字节一致、新帖首张字图 200（对照：不存在的路径必须 404）
U=https://ziku.xlingdata.com
enc(){ python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$1"; }
L=$(curl -sf "$U/$(enc 网站/db.js)?t=$(date +%s)" | md5sum | cut -d' ' -f1)
R=$(md5sum "$REL/网站/db.js" | cut -d' ' -f1)
[ "$L" = "$R" ] || { echo "回读 db.js 不一致 $L != $R" >&2; exit 3; }
G=$(ls "$REL/$BOOK/glyphs" | head -1)
[ "$(curl -s -o /dev/null -w '%{http_code}' "$U/$(enc "$BOOK/glyphs/$G")")" = 200 ] || { echo "字图取不到" >&2; exit 4; }
[ "$(curl -s -o /dev/null -w '%{http_code}' "$U/$(enc "$BOOK/glyphs/nope.png")")" = 404 ] || { echo "404 对照失败，探针不可信" >&2; exit 5; }
echo "上线完成：db.js $L，$BOOK"
