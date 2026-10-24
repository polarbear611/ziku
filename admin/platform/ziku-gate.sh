#!/bin/bash
# platform 上「发布密钥」的强制命令（authorized_keys 里 command="/home/op/ziku-admin/ziku-gate.sh"）
# 这把钥匙只能做两件事：
#   1) rsync 收货到 ~/ziku-admin/incoming/<任务号>/       （不能读、不能写别处、不能带长选项）
#   2) promote <任务号>  -> promote.py 校验后上架           （只替换一部帖的目录和 db.js，先备份）
set -u
cd /home/op/ziku-admin || exit 1
CMD="${SSH_ORIGINAL_COMMAND:-}"
log(){ echo "$(date '+%F %T') $*" >> gate.log; }
JID='[0-9]{14}-[0-9a-f]{6}'
read -r -a T <<< "$CMD"
if [[ ${#T[@]} -eq 5 && ${T[0]} == rsync && ${T[1]} == --server && ${T[2]} =~ ^-[A-Za-z.]+$ \
      && ${T[3]} == . && ${T[4]} =~ ^incoming/${JID}/?$ ]]; then
  mkdir -p "${T[4]}"
  log "recv ${T[4]}"
  exec rsync --server "${T[2]}" . "${T[4]}"
elif [[ ${#T[@]} -eq 2 && ${T[0]} == promote && ${T[1]} =~ ^${JID}$ ]]; then
  log "promote ${T[1]}"
  exec python3 promote.py "${T[1]}"
fi
log "DENY $CMD"
echo "denied" >&2
exit 1
