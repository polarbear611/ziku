# 释文初稿：通行释文（books/<帖>/baseline.txt）+ 页面图 -> 逐页逐列的 tokens（books/<帖>/text/pNN.tokens）
# 适用于字距规整的楷书/碑帖：每页按墨迹投影粗切成字格 -> 每格送识别模型打分 ->
# 全书所有字格与通行释文做一次全局编辑距离对齐（字格 = 某字 / 废格；释文字 = 落在某格 / 图上缺失），
# 于是每页从哪个字开始、每列几个字都由对齐给出。初稿仍需对图人工核对（异体写法、残损字）。
# 用法: ZIKU_BOOK=jcg python seed_text.py 1 48   -> text/pNN.tokens + text/seed_report.txt
import json, os, sys
import cv2
import numpy as np
from scipy.signal import find_peaks
import align
import ocrscore as O

JUNK, MISS, CAP = 5.0, 7.0, 9.0

def cells(pid):
    """-> [(列号, x0, y0, x1, y1)]，列右->左、列内上->下"""
    img = cv2.imread(f'{align.PAGES}/{pid}.png')
    b = align.binarize(img)
    H, W = b.shape
    prof = align.smooth(b.sum(0).astype(float), 15)
    pk, _ = find_peaks(prof, distance=W * 0.15, prominence=prof.max() * 0.12)
    pk = np.sort(pk)[::-1]
    pitch = float(np.median(np.abs(np.diff(pk)))) if len(pk) > 1 else W / 4
    out = []
    for c, x in enumerate(pk):
        x0, x1 = int(max(0, x - pitch * 0.48)), int(min(W, x + pitch * 0.48))
        yp = b[:, x0:x1].sum(1)
        ink = yp > 1
        runs, y = [], 0
        while y < H:
            if ink[y]:
                e = y
                while e < H and ink[e]: e += 1
                runs.append([y, e]); y = e
            else:
                y += 1
        # 相邻墨段合并成字：合并后不超过 1.1 个字距、空隙小于 0.2 个字距
        merged = True
        while merged and len(runs) > 1:
            merged = False
            gaps = [(runs[i + 1][0] - runs[i][1], i) for i in range(len(runs) - 1)]
            for g, i in sorted(gaps):
                if runs[i + 1][1] - runs[i][0] <= pitch * 1.0 and g < pitch * 0.2:
                    runs[i:i + 2] = [[runs[i][0], runs[i + 1][1]]]; merged = True; break
        for y0, y1 in runs:
            if y1 - y0 < pitch * 0.12 and yp[y0:y1].sum() < 0.02 * pitch * pitch * 0.3:
                continue
            xs = np.where(b[y0:y1, x0:x1].any(0))[0]
            out.append((c, x0 + int(xs[0]), y0, x0 + int(xs[-1]) + 1, y1))
    return img, out

def main():
    a, z = int(sys.argv[1]), int(sys.argv[2])
    base = [l.strip() for l in open(f'{align.BOOKDIR}/baseline.txt') if l.strip()]
    chars = [c for l in base for c in l]
    allc, crops = [], []
    for n in range(a, z + 1):
        pid = f'p{n:02d}'
        img, cs = cells(pid)
        for c in cs:
            x0, y0, x1, y1 = c[1:]
            crops.append(img[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4])
            allc.append((pid,) + c)
    P = O.probs(crops)
    ids = [O.char_ids(ch) for ch in chars]
    E = np.full((len(allc), len(chars)), CAP)
    for j, d in enumerate(ids):
        if d:
            E[:, j] = np.minimum(CAP, -np.log(P[:, d].max(1) + 1e-6))
        else:
            E[:, j] = 3.0                                 # 识别字典外的字：中性代价
    n, m = E.shape
    D = np.zeros((n + 1, m + 1)); Bk = np.zeros((n + 1, m + 1), np.int8)
    D[1:, 0] = np.arange(1, n + 1) * JUNK; Bk[1:, 0] = 1
    D[0, 1:] = np.arange(1, m + 1) * MISS; Bk[0, 1:] = 2
    for i in range(1, n + 1):
        diag = D[i - 1, :-1] + E[i - 1]
        up = D[i - 1, 1:] + JUNK
        best = np.minimum(diag, up); bk = np.where(diag <= up, 0, 1)
        row = np.empty(m + 1); row[0] = D[i, 0]
        for j in range(1, m + 1):                         # 横向（缺字）只能逐个递推
            v = row[j - 1] + MISS
            if v < best[j - 1]:
                row[j] = v; Bk[i, j] = 2
            else:
                row[j] = best[j - 1]; Bk[i, j] = bk[j - 1]
        D[i] = row
    i, j, path = n, m, []
    while i > 0 or j > 0:
        k = Bk[i, j]
        if k == 0: path.append(('m', i - 1, j - 1)); i -= 1; j -= 1
        elif k == 1: path.append(('junk', i - 1, None)); i -= 1
        else: path.append(('miss', None, j - 1)); j -= 1
    path = path[::-1]
    # 落页落列：缺字跟随前一个已落格的字
    pages, rep, last = {}, [], None
    for kind, ci, cj in path:
        if kind == 'junk':
            pid, c = allc[ci][:2]
            rep.append(f'{pid} 列{c} 废格 识别={O.top(P[ci], 1)[0][0]}')
            continue
        if kind == 'm':
            pid, c = allc[ci][:2]; last = (pid, c)
            p = float(np.exp(-E[ci, cj]))
            if p < 0.05 and ids[cj]:
                rep.append(f'{pid} 列{c} 「{chars[cj]}」低分 p={p:.3f} 识别={O.top(P[ci], 1)[0][0]}')
        else:
            pid, c = last if last else (allc[0][0], 0)
            rep.append(f'{pid} 列{c} 缺字「{chars[cj]}」（释文有、图上没对上）')
        pages.setdefault(pid, {}).setdefault(c, []).append(chars[cj])
    os.makedirs(align.TEXT, exist_ok=True)
    for pid, cols in pages.items():
        open(f'{align.TEXT}/{pid}.tokens', 'w').write(
            '\n'.join(' '.join(cols[c]) for c in sorted(cols)) + '\n')
    open(f'{align.TEXT}/seed_report.txt', 'w').write('\n'.join(rep) + '\n')
    nm = sum(1 for k, _, _ in path if k == 'm')
    print(f'字格 {n}，释文 {m} 字：对上 {nm}，废格 {n - nm}，缺字 {m - nm}；写出 {len(pages)} 页 -> {align.TEXT}')

if __name__ == '__main__':
    main()
