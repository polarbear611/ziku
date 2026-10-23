#!/usr/bin/env bash
# 逐页跑 v2 全流程：对齐 -> 夹注定位 -> 单字成品图 -> 矢量化
# 用法: ./run_pages.sh p02 p03 ...   日志写 out3/<pid>.log
cd "$(dirname "$0")" && mkdir -p out3
for p in "$@"; do
  rm -f out3/${p}_raw.json
  { venv/bin/python align3.py $p && venv/bin/python refine.py $p && venv/bin/python glyph.py $p && venv/bin/python vector.py $p; } > out3/$p.log 2>&1 \
    && echo "$p ok: $(tail -1 out3/$p.log)" || echo "$p FAIL (see out3/$p.log)"
done
