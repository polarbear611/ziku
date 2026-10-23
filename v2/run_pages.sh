#!/usr/bin/env bash
# 逐页跑 v2 全流程：对齐 -> 夹注定位 -> 单字成品图 -> 矢量化
# 用法: [ZIKU_BOOK=jcg] ./run_pages.sh p02 p03 ...   日志写 <输出目录>/<pid>.log（保母帖是 out3/）
cd "$(dirname "$0")" || exit 1
OUT=$(venv/bin/python -c 'import align; print(align.OUT3)') || exit 1
mkdir -p "$OUT"
for p in "$@"; do
  rm -f "$OUT/${p}_raw.json"
  { venv/bin/python align3.py $p && venv/bin/python refine.py $p && venv/bin/python glyph.py $p && venv/bin/python vector.py $p; } > "$OUT/$p.log" 2>&1 \
    && echo "$p ok: $(tail -1 "$OUT/$p.log")" || echo "$p FAIL (see $OUT/$p.log)"
done
