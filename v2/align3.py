# v2 第三段：整页对齐（在 align2 的基础上）
# - 整页文字是一条序列，列间的字数分配由 DP 决定（tokens 的换列位置允许 ±3 字偏差）
# - 文字有而图上没有 -> 「缺字」（固定代价 DEL，进复核队列）
# - 图上有而文字没有 -> 「废段」（校改符号/污渍/漏录字，固定代价 JUNK，进复核队列）
# 于是转录里的多字、漏字、换列错位都只影响局部，不会让整列错位
# 用法: python align3.py p02 [p03 ...] -> out/<pid>.json, <pid>_junk.json, <pid>_ov.jpg
import cv2, json, sys
import numpy as np
import align
import ocrscore as O

JUNK = 6.0
DEL = 12.0
EMCAP = 8.0       # 单字识别代价上限：认不出的字也要比「判缺字」便宜
UNK = 2.5
MAXSPAN = 8
SHIFT = 8
import os
OUT = align.OUT3
os.makedirs(OUT, exist_ok=True)

def prepare(img, b, x0, x1, seq_hint):
    """列内：几何 DP 定尺度 -> 候选切点 -> 所有可行段的识别概率"""
    from align2 import candidates
    segs0, s = align.align_column(b, x0, x1, seq_hint)
    prof = b[:, x0:x1].sum(1).astype(float)
    H = len(prof)
    Y0 = min(min(t0 for _, _, t0, _ in segs0), segs0[0][0])
    Y1 = max(max(t1 for _, _, _, t1 in segs0) + 1, segs0[-1][1])
    prof[:Y0] = 0; prof[Y1:] = 0
    ink = prof > 1
    nxt = np.full(H + 1, H, int); prv = np.full(H + 1, -1, int)
    last = H
    for y in range(H - 1, -1, -1):
        if ink[y]: last = y
        nxt[y] = last
    last = -1
    for y in range(H):
        if ink[y]: last = y
        prv[y] = last
    ps = align.smooth(prof, 5); ps[~ink & (ps < 1)] = 0
    rowink = float(np.median(prof[ink]))
    cp = np.concatenate([[0], np.cumsum(prof)])
    C = candidates(ps, Y0, Y1, rowink, [a for a, _, _, _ in segs0] + [segs0[-1][1]])
    M = len(C)
    hmax = s * 0.95 * 2.2
    segs = {}
    crops = []
    for i in range(M):
        for j in range(i + 1, min(M, i + MAXSPAN + 1)):
            t0, t1 = nxt[C[i]], prv[C[j] - 1]
            h = t1 - t0 + 1
            if h < 3: continue
            if h > hmax: break
            cx0, cx1 = align.char_box(b, x0, x1, t0, t1)
            p = 4
            crops.append(img[max(0, t0 - p):t1 + 1 + p, max(0, cx0 - p):cx1 + p])
            z = ~ink[t0:t1 + 1]
            g = 0
            if z.any():
                d = np.diff(np.concatenate([[0], z.astype(int), [0]]))
                g = int((np.where(d == -1)[0] - np.where(d == 1)[0]).max())
            segs[(i, j)] = (len(crops) - 1, (int(cx0), int(t0), int(cx1), int(t1)), g)
    P = O.probs(crops)
    return {'C': C, 'M': M, 's': s, 'segs': segs, 'P': P,
            'cutc': ps[C] / rowink * 1.5,
            'head': 3.0 * (cp[C] - cp[Y0]) / (rowink * 20),
            'tail': 3.0 * (cp[Y1] - cp[C]) / (rowink * 20)}

def col_dp(pr, seq):
    """列内对 seq 做编辑距离式对齐。返回 cost[k]（恰好消耗前 k 字的最优代价）与回溯所需表"""
    C, M, s, segs, P, cutc = pr['C'], pr['M'], pr['s'], pr['segs'], pr['P'], pr['cutc']
    N = len(seq)
    r = [align.glyph_ratio(c)[0] * (0.55 if note else 1.0) for c, note in seq]
    rw = [align.glyph_ratio(c)[1] * (0.55 if note else 1.0) for c, note in seq]
    ids = [O.char_ids(c) if not note else [] for c, note in seq]
    INF = 1e18
    D = np.full((N + 1, M), INF)
    B = {}
    D[0] = pr['head']
    for k in range(N + 1):
        if k > 0:                                   # 缺字：不占段
            for j in range(M):
                c = D[k - 1, j] + DEL
                if c < D[k, j]:
                    D[k, j] = c; B[(k, j)] = ('del', k - 1, j)
        for j in range(M):
            if k > 0:
                e = s * r[k - 1]
                for i in range(max(0, j - MAXSPAN), j):
                    if D[k - 1, i] >= INF: continue
                    sg = segs.get((i, j))
                    if sg is None: continue
                    q, (cx0, t0, cx1, t1), g = sg
                    gap = 20 * max(0.0, g / s - 0.15)     # 段内大空白 -> 多半是两个字
                    em = -np.log(P[q, ids[k - 1]].max() + 1e-6) if ids[k - 1] else UNK
                    c = D[k - 1, i] + min(em, EMCAP) + gap + 0.6 * np.log((t1 - t0 + 1) / e) ** 2 \
                        + 0.6 * min(0.0, np.log((cx1 - cx0) / (s * rw[k - 1]) / 0.8)) ** 2 + cutc[j]
                    if c < D[k, j]:
                        D[k, j] = c; B[(k, j)] = ('char', k - 1, i)
            for i in range(max(0, j - MAXSPAN), j):     # 废段
                if D[k, i] >= INF or (i, j) not in segs: continue
                c = D[k, i] + JUNK + cutc[j]
                if c < D[k, j]:
                    D[k, j] = c; B[(k, j)] = ('junk', k, i)
    endc = D + pr['tail'][None, :]
    jbest = endc.argmin(1)
    return endc[np.arange(N + 1), jbest], (D, B, jbest)

def backtrack(pr, seq, tables, k):
    D, B, jbest = tables
    j = int(jbest[k])
    out = []
    while (k, j) in B:
        kind, pk, i = B[(k, j)]
        if kind == 'char':
            out.append(('char', k - 1, pr['segs'][(i, j)]))
        elif kind == 'junk':
            out.append(('junk', None, pr['segs'][(i, j)]))
        else:
            out.append(('del', k - 1, None))
        k, j = pk, i
    return out[::-1]

def run(pid):
    img = cv2.imread(f'{align.PAGES}/{pid}.png')
    b = align.binarize(img)
    texts = align.column_texts(pid)
    cols = align.find_columns(b, len(texts))
    # tokens 整行为「-」的列（如与上一页重复的首列）不参与对齐
    keep = [i for i, t in enumerate(texts) if t]
    cols = [cols[i] for i in keep]; texts = [texts[i] for i in keep]
    # 注文（双行小字）不进 DP，免得它们廉价地吃掉正文字的墨；由 refine.py 单独定位
    gidx, notes, n = [], [], 0          # gidx: 正文第 i 字在全页释文里的序号
    for c, t in enumerate(texts):
        for ch, note in t:
            if note:
                notes.append({'col': c, 'idx': n, 'char': ch, 'note': True,
                              'x': 0, 'y': 0, 'w': 0, 'h': 0, 'p': None, 'top': []})
            else:
                gidx.append(n)
            n += 1
    texts = [[x for x in t if not x[1]] for t in texts]
    seq = [x for t in texts for x in t]
    L = len(seq)
    A = np.cumsum([0] + [len(t) for t in texts])        # tokens 给的换列位置
    nC = len(cols)
    preps = [prepare(img, b, x0, x1, t) for (x0, x1), t in zip(cols, texts)]
    # 页级 DP：F[c][a] = 前 c 列消耗 a 字的最优代价
    INF = 1e18
    F = [dict() for _ in range(nC + 1)]
    F[0][0] = (0.0, None)
    cache = {}
    for c in range(nC):
        for a, (fa, _) in F[c].items():
            hi = min(L, A[c + 1] + SHIFT) if c < nC - 1 else L
            lo = max(a, A[c + 1] - SHIFT) if c < nC - 1 else L
            sub = seq[a:hi]
            cost, tables = col_dp(preps[c], sub)
            cache[(c, a)] = (sub, tables)
            for e in range(lo, hi + 1):
                v = fa + cost[e - a]
                if v < F[c + 1].get(e, (INF,))[0]:
                    F[c + 1][e] = (v, a)
    # 回溯列分配
    e = L; alloc = []
    for c in range(nC, 0, -1):
        a = F[c][e][1]; alloc.append((a, e)); e = a
    alloc = alloc[::-1]
    res, junks, dels = [], [], []
    ov = img.copy()
    for c, (a, e) in enumerate(alloc):
        sub, tables = cache[(c, a)]
        path = backtrack(preps[c], sub, tables, e - a)
        P = preps[c]['P']
        moved = (a != A[c]) or (e != A[c + 1])
        for kind, k, sg in path:
            if kind == 'del':
                ch, note = sub[k]
                dels.append({'col': c, 'idx': gidx[a + k], 'char': ch})
                continue
            q, (cx0, t0, cx1, t1), _ = sg
            box = {'col': c, 'x': cx0, 'y': t0, 'w': cx1 - cx0, 'h': t1 - t0 + 1, 'top': O.top(P[q])}
            if kind == 'junk':
                junks.append(box)
                cv2.rectangle(ov, (cx0, t0), (cx1, t1), (255, 0, 255), 2)
                continue
            ch, note = sub[k]
            p = O.score(P[q], ch) if not note else None
            it = dict(box, idx=gidx[a + k], char=ch, note=note, p=None if p is None else round(p, 4))
            res.append(it)
            low = p is None or p < 0.3
            cv2.rectangle(ov, (cx0, t0), (cx1, t1), (0, 0, 255) if low else (0, 160, 0), 2)
        print(f'{pid} 列{c} 字[{a},{e}) tokens[{A[c]},{A[c+1]}){" ←换列调整" if moved else ""}')
    for d in dels:
        print(f'  缺字(文字有图上无): 列{d["col"]} 「{d["char"]}」 序号{d["idx"]}')
    print(f'  废段(图上有文字无): {len(junks)}  页代价 {F[nC][L][0]:.1f}')
    res = sorted(res + notes, key=lambda t: t['idx'])
    json.dump(res, open(f'{OUT}/{pid}.json', 'w'), ensure_ascii=False, indent=1)
    json.dump({'junk': junks, 'del': dels}, open(f'{OUT}/{pid}_extra.json', 'w'), ensure_ascii=False, indent=1)
    cv2.imwrite(f'{OUT}/{pid}_ov.jpg', cv2.resize(ov, (1000, int(ov.shape[0] * 1000 / ov.shape[1]))))

if __name__ == '__main__':
    for pid in sys.argv[1:]:
        run(pid)
