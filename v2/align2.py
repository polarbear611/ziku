# v2 第二段：识别打分驱动的强制对齐
# 1) align.align_column 几何 DP 得到尺度 s 和初始切点
# 2) 候选切点 = 墨迹投影谷底/空白带中点 + 初始切点
# 3) DP：每列 N 个字依次占用候选切点之间的段，段代价 = -log P(该字|字图)（PP-OCRv4）
#    + 高度先验 + 切墨代价；允许「废段」（校改符号、污渍）以固定代价跳过
# 4) 输出每字 p（标签概率）与 top3，p 低的进人工复核队列
# 用法: python align2.py p02 [p03 ...]  -> out/<pid>.json + out/<pid>_ov.jpg
import cv2, json, sys
import numpy as np
import align
import ocrscore as O

STEP = 3
JUNK = 6.0          # 废段固定代价 ≈ -log(0.0025)
UNK = 2.5           # 字典外的字（如 歟）/夹注 的识别代价
MAXSPAN = 8         # 一个字最多跨几个候选切点

def candidates(ps, Y0, Y1, rowink, extra):
    c = set(extra) | {Y0, Y1}
    y = Y0
    while y < Y1:                                   # 空白带取中点
        if ps[y] == 0:
            e = y
            while e < Y1 and ps[e] == 0: e += 1
            c.add((y + e) // 2); y = e
        else:
            y += 1
    for y in range(Y0 + 6, Y1 - 6):                 # 墨迹谷底（粘连处）
        w = ps[y - 6:y + 7]
        if ps[y] > 0 and ps[y] == w.min() and ps[y] < 0.6 * rowink:
            c.add(y)
    c = sorted(c)
    out = [c[0]]
    for y in c[1:]:
        if y - out[-1] >= 5: out.append(y)
    return np.array(out)

def align_column(img, b, x0, x1, seq):
    segs0, s = align.align_column(b, x0, x1, seq)
    col = b[:, x0:x1]
    prof = col.sum(1).astype(float)
    H = len(prof)
    # 与几何阶段一致的有效范围
    Y0 = min(t0 for _, _, t0, _ in segs0); Y1 = max(t1 for _, _, _, t1 in segs0) + 1
    Y0 = min(Y0, segs0[0][0]); Y1 = max(Y1, segs0[-1][1])
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
    extra = [a for a, _, _, _ in segs0] + [segs0[-1][1]]
    C = candidates(ps, Y0, Y1, rowink, extra)
    M = len(C)
    N = len(seq)
    r = np.array([align.glyph_ratio(c)[0] * (0.55 if note else 1.0) for c, note in seq])
    hmax = s * max(r.max(), 0.9) * 2.2

    # 所有可行段 -> 字图 -> 识别概率
    pairs, crops, boxes = [], [], []
    for i in range(M):
        for j in range(i + 1, min(M, i + MAXSPAN + 1)):
            t0, t1 = nxt[C[i]], prv[C[j] - 1]
            h = t1 - t0 + 1
            if h < 3: continue
            if h > hmax: break
            cx0, cx1 = align.char_box(b, x0, x1, t0, t1)
            p = 4
            crops.append(img[max(0, t0 - p):t1 + 1 + p, max(0, cx0 - p):cx1 + p])
            pairs.append((i, j)); boxes.append((cx0, t0, cx1, t1))
    P = O.probs(crops)
    seg = {pr: k for k, pr in enumerate(pairs)}
    ids = [O.char_ids(c) if not note else [] for c, note in seq]

    INF = 1e18
    D = np.full((N + 1, M), INF); B = np.full((N + 1, M, 2), -1, int)
    cutc = ps[C] / rowink * 1.5
    D[0] = 3.0 * (cp[C] - cp[Y0]) / (rowink * 20)
    for k in range(N + 1):
        for j in range(M):
            if k > 0:
                e = s * r[k - 1]
                for i in range(max(0, j - MAXSPAN), j):
                    if D[k - 1, i] >= INF or (i, j) not in seg: continue
                    q = seg[(i, j)]
                    h = boxes[q][3] - boxes[q][1] + 1
                    em = -np.log(P[q, ids[k - 1]].max() + 1e-6) if ids[k - 1] else UNK
                    c = D[k - 1, i] + min(em, 14) + 0.6 * np.log(h / e) ** 2 + cutc[j]
                    if c < D[k, j]:
                        D[k, j] = c; B[k, j] = (k - 1, i)
            for i in range(max(0, j - MAXSPAN), j):     # 废段
                if D[k, i] >= INF or (i, j) not in seg: continue
                c = D[k, i] + JUNK + cutc[j]
                if c < D[k, j]:
                    D[k, j] = c; B[k, j] = (k, i)
    tail = 3.0 * (cp[Y1] - cp[C]) / (rowink * 20)
    j = int(np.argmin(D[N] + tail)); k = N
    path = []
    while True:
        pk, i = B[k, j]
        if pk < 0: break
        path.append((pk < k, k - 1 if pk < k else None, i, j))
        k, j = pk, i
    path = path[::-1]
    items, junk = [], []
    for is_char, kk, i, j in path:
        q = seg[(i, j)]
        cx0, t0, cx1, t1 = boxes[q]
        if is_char:
            ch, note = seq[kk]
            p = O.score(P[q], ch) if not note else None
            items.append({'k': int(kk), 'char': ch, 'note': note, 'x': int(cx0), 'y': int(t0),
                          'w': int(cx1 - cx0), 'h': int(t1 - t0 + 1),
                          'p': None if p is None else round(p, 4), 'top': O.top(P[q])})
        else:
            junk.append({'x': int(cx0), 'y': int(t0), 'w': int(cx1 - cx0), 'h': int(t1 - t0 + 1),
                         'top': O.top(P[q])})
    return items, junk

def run(pid):
    img = cv2.imread(f'{align.WORK}/pages/{pid}.png')
    b = align.binarize(img)
    texts = align.column_texts(pid)
    cols = align.find_columns(b, len(texts))
    res, junks = [], []
    ov = img.copy()
    for ci, ((x0, x1), seq) in enumerate(zip(cols, texts)):
        items, junk = align_column(img, b, x0, x1, seq)
        for it in items:
            it['col'] = ci; res.append(it)
            low = it['p'] is None or it['p'] < 0.3
            color = (0, 160, 0) if not low else (0, 0, 255)
            cv2.rectangle(ov, (it['x'], it['y']), (it['x'] + it['w'], it['y'] + it['h']), color, 2)
        for jk in junk:
            jk['col'] = ci; junks.append(jk)
            cv2.rectangle(ov, (jk['x'], jk['y']), (jk['x'] + jk['w'], jk['y'] + jk['h']), (255, 0, 255), 2)
        lows = sum(1 for it in items if it['p'] is None or it['p'] < 0.3)
        print(f'{pid} 列{ci} 字数={len(seq)} 低分={lows} 废段={len(junk)}')
    json.dump(res, open(f'{align.OUT}/{pid}.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(junks, open(f'{align.OUT}/{pid}_junk.json', 'w'), ensure_ascii=False, indent=1)
    cv2.imwrite(f'{align.OUT}/{pid}_ov.jpg', cv2.resize(ov, (1000, int(ov.shape[0] * 1000 / ov.shape[1]))))

if __name__ == '__main__':
    for pid in sys.argv[1:]:
        run(pid)
