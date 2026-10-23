# 单字成品图：对齐结果 -> 只含本字墨迹的透明图 + 统一规格
# 1) 墨迹归属按连通域：横向主要落在本列字轴之外的（旁注、校改符号、邻列笔画）不要；
#    纵向大部分落在本字范围内的整块归本字（伸出切线的笔画不被切断），跨两字的才按切线分
# 2) 统一规格：整页一个字身尺寸 S（由墨迹长边的 90 分位定），字的墨迹中心放在方格中心，不按单字缩放，
#    保留原帖字与字的大小关系；超出方格的才整体缩小
# 3) 透明：alpha 取自「纸色 - 灰度」，保留笔画边缘的浓淡
# 用法: python glyph.py p01 -> glyph/p01/<idx>.png（RGBA, OUTPX 方图）+ glyph/p01/meta.json
import cv2, json, os, sys
import numpy as np
import align

OUT3 = align.OUT3
GL = align.GL
FILL = 0.86        # 字身 S：使 90% 的字墨迹长边 ≤ S × FILL，其余整体缩小
WEAK = 12          # 弱阈：纸色差 > WEAK 的淡墨，只要与本字强墨相连就并入（滞后阈值，补回飞白/淡笔）
FAINTA = 30        # 不相连的淡墨块面积下限（像素）
OUTPX = 256
AXIS = 0.45        # 字轴半宽（× 中位字宽），连通域与此区间横向重叠不足 OVL 视为旁物
OVL = 0.3
OWN = 0.85         # 连通域 ≥85% 落在某字纵向范围内 -> 整块归该字
CUTA = 0.04        # 跨字墨块两侧都超过 CUTA × 字高² 才视为两字粘连、按分界切
ZONE = 0.35        # 离分界 < ZONE × 字高 的小墨块算「归属待定」
BIG = 0.06         # 面积 ≥ BIG × 字高² 的墨块即使靠近分界也算该字主体
LINEH = 4          # 高 ≤ LINEH 且细长的墨块视为框线碎片
A0 = 8             # 纸色差 -> alpha：A0 以下全透明
A1MIN, FULL = 28, 0.75   # 满墨点 = max(A1MIN, 本字强墨 90 分位 × FULL)
GROW, GROWN = 9, 12      # 沿笔画生长：纸色差 > GROW 的相邻像素，最多 GROWN 步
RULEL = 45               # 长于此（像素）的横/竖淡线视为界格线，不往里长

def ranges(items):
    """同列相邻两字之间取空白中线作分界，返回每字纵向归属范围 [lo, hi)"""
    r = []
    for k, it in enumerate(items):
        lo = (items[k - 1]['y'] + items[k - 1]['h'] + it['y']) // 2 if k else it['y'] - 40
        hi = (it['y'] + it['h'] + items[k + 1]['y']) // 2 if k + 1 < len(items) else it['y'] + it['h'] + 40
        r.append((lo, hi))
    return r

def assign(lab, st, its, s, sw):
    """一列内墨块 -> 字。返回 {id(字): [(墨块号, None | (行lo,行hi))]}
    规则（按优先级）：
    1. 注文框内的墨块归注文；横向基本在字轴外的（旁注/符号/邻列笔画）、细长框线碎片丢弃
    2. 两字真粘连（跨分界且两侧面积都 ≥ CUTA·s²）-> 按分界切开
    3. 主体墨块（≥OWN 落在某字范围内，且是该字的大块或远离分界）-> 归该字
    4. 其余靠近分界的离散部件 -> 归「主体离它最近」的那个字（字内部件间距 < 字间距）"""
    notes = [t for t in its if t.get('note')]
    body = sorted([t for t in its if not t.get('note')], key=lambda t: t['y'])
    rg = ranges(body)
    ax = float(np.median([t['x'] + t['w'] / 2 for t in body if not t.get('junk')] or [0]))
    half = AXIS * sw
    Y0, Y1 = rg[0][0], rg[-1][1]
    win = lab[max(0, Y0):Y1, max(0, int(ax - sw)):int(ax + sw)]
    own = {}
    zone = ZONE * s
    core = {}                                             # 字序号 -> [墨块号]
    amb = []
    for i in np.unique(win):
        if not i: continue
        X, Y, W, H, A = st[i]
        cy, cx = Y + H / 2, X + W / 2
        nb = next((t for t in notes if t['x'] - 3 <= cx <= t['x'] + t['w'] + 3 and t['y'] - 3 <= cy <= t['y'] + t['h'] + 3), None)
        if nb is not None:
            own.setdefault(id(nb), []).append((i, None)); continue
        ov = max(0, min(X + W, ax + half) - max(X, ax - half))
        if ov < OVL * W and (W < sw or ov == 0):          # 宽墨块只要碰到字轴带就留（长横）；完全不碰的是邻列的字
            continue
        if H <= LINEH and W >= 4 * H and W >= 12:         # 框线碎片
            continue
        rows = np.bincount((np.where(lab[Y:Y + H, X:X + W] == i)[0] + Y), minlength=Y + H)[Y:]
        fr = np.array([rows[max(0, lo - Y):max(0, hi - Y)].sum() for lo, hi in rg], float) / A
        k = int(fr.argmax())
        lo, hi = rg[k]
        side = sorted(range(len(rg)), key=lambda j: -fr[j])
        if fr[side[1]] * A >= CUTA * s * s and fr[k] * A >= CUTA * s * s:   # 粘连：按分界切
            for j in range(len(rg)):
                if fr[j] > 0:
                    own.setdefault(id(body[j]), []).append((i, rg[j]))
                    core.setdefault(j, []).append(i)
            continue
        near = (Y - lo < zone and k > 0) or (hi - (Y + H) < zone and k < len(rg) - 1)
        if fr[k] >= OWN and (not near or A >= BIG * s * s):
            core.setdefault(k, []).append(i)
            own.setdefault(id(body[k]), []).append((i, None))
        else:
            amb.append((i, k, fr[k]))
    # 全由小块组成的字（六、二、上…）没有主体：把基本落在它范围内（≥OWN）的待定墨块升为主体；
    # 压在分界上的仍留给下面的聚类
    for k in {k for _, k, _ in amb if not core.get(k)}:
        mine = [i for i, kk, f in amb if kk == k and f >= OWN]
        if not mine:
            mine = [i for i, kk, f in amb if kk == k]
        core[k] = mine
        own.setdefault(id(body[k]), []).extend((i, None) for i in mine)
    amb = [(i, k) for i, k, _ in amb if i not in core.get(k, [])]
    # 离散部件：带约束的单链聚类（Kruskal）——墨块间距离从小到大依次合并，
    # 但不合并已属于两个不同字的簇；最后每簇归其所属字（无归属的归多数一侧）。
    # 字内部件间距 < 字间距，所以部件会先经由同字的其它小块连上本字
    left = {i: k for i, k in amb}
    near_ids = set(left) | {i for v in core.values() for i in v}
    R = int(ZONE * s * 2)
    edges = []
    for i in left:                                    # 待定墨块到其附近墨块的像素距离
        X, Y, W, H, _ = st[i]
        y0, x0 = max(0, Y - R), max(0, X - R)
        sub = lab[y0:Y + H + R, x0:X + W + R]
        dt = cv2.distanceTransform((sub != i).astype(np.uint8), cv2.DIST_L2, 3)
        for j in np.unique(sub):
            if j and j != i and j in near_ids:
                edges.append((float(dt[sub == j].min()), int(i), int(j)))
    par = {i: i for i in near_ids}
    tag = {}                                           # 簇根 -> 字序号
    for k, v in core.items():
        for i in v: tag[i] = k
    def root(i):
        while par[i] != i:
            par[i] = par[par[i]]; i = par[i]
        return i
    for d, i, j in sorted(edges):
        ri, rj = root(i), root(j)
        if ri == rj: continue
        ti, tj = tag.get(ri), tag.get(rj)
        if ti is not None and tj is not None and ti != tj: continue
        kk = left.get(i, left.get(j))
        t = ti if ti is not None else tj
        if t is not None and kk is not None and abs(t - kk) > 1: continue   # 只跨一个分界
        par[ri] = rj
        if t is not None: tag[rj] = t
    for i, k in left.items():
        best = tag.get(root(i), k)
        own.setdefault(id(body[best]), []).append((i, None))
    return own

def run(pid):
    img = cv2.imread(f'{align.PAGES}/{pid}.png')
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = cv2.medianBlur(gray.astype(np.uint8), 61).astype(np.float32)
    dark = bg - gray
    b = align.binarize(img)
    weak = ((dark > WEAK) & ~cv2.dilate(align.red_mask(img), np.ones((3, 3), np.uint8)).astype(bool)).astype(np.uint8)
    for k in ((120, 1), (1, 120)):                       # 弱墨里同样去掉框线
        ln = cv2.morphologyEx(weak, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        weak[cv2.dilate(ln, np.ones((5, 5), np.uint8)) > 0] = 0
    wn, wlab = cv2.connectedComponents(weak, connectivity=8)
    # 生长禁区：界格线（较短的直线核，淡线也能检出）
    lw = (dark > GROW).astype(np.uint8)
    rule = np.zeros_like(lw)
    for k in ((RULEL, 1), (1, RULEL)):
        rule |= cv2.morphologyEx(lw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
    rule = cv2.dilate(rule, np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    items = json.load(open(f'{OUT3}/{pid}.json'))
    ex = json.load(open(f'{OUT3}/{pid}_extra.json'))
    items = [it for it in items if it['w'] > 0]           # 未能定位的注文跳过
    main = [it for it in items if not it['note']]
    hs = np.array([it['h'] for it in main]); ws = np.array([it['w'] for it in main])
    s = float(np.median(hs)); sw = float(np.median(ws))
    S = int(round(np.percentile(np.maximum(hs, ws), 90) / FILL))
    os.makedirs(f'{GL}/{pid}', exist_ok=True)
    meta = {'S': S, 'scale': OUTPX / S, 'items': []}
    # 每列：字轴、纵向归属范围（废段也参与分界，免得它的墨被并进邻字）
    bycol = {}
    for it in items + [dict(j, junk=True) for j in ex['junk']]:
        bycol.setdefault(it['col'], []).append(it)
    for c, its in bycol.items():
        own = assign(lab, st, its, s, sw)
        for it in its:
            if it.get('junk'):
                continue
            mask = np.zeros_like(b)
            for i, rows in own.get(id(it), []):
                X, Y, W, H, A = st[i]
                cm = (lab[Y:Y + H, X:X + W] == i).astype(np.uint8)
                if rows is not None:                          # 两字粘连的墨块：只取本字分界内的行
                    cm[:max(0, rows[0] - Y)] = 0; cm[max(0, rows[1] - Y):] = 0
                mask[Y:Y + H, X:X + W] |= cm
            ys, xs = np.where(mask)
            if len(ys) == 0:
                continue
            gy0, gy1, gx0, gx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            # 滞后阈值：与本字强墨相连的弱墨连通域整体并入（只在本字范围内）
            wy0, wy1, wx0, wx1 = max(0, gy0 - 6), gy1 + 6, max(0, gx0 - 6), gx1 + 6
            wl = wlab[wy0:wy1, wx0:wx1]
            hit = np.unique(wl[mask[wy0:wy1, wx0:wx1] > 0])
            # 不与强墨相连、但整块落在本字墨迹框内的淡墨（极淡的笔画）也并入
            ids_, cnt = np.unique(wl, return_counts=True)
            inner = wl[6:-6, 6:-6] if wl.shape[0] > 12 and wl.shape[1] > 12 else wl
            ic = dict(zip(*np.unique(inner, return_counts=True)))
            hit = np.union1d(hit, [i for i, c in zip(ids_, cnt) if i and c >= FAINTA and ic.get(i, 0) >= 0.9 * c])
            m = mask.copy()
            m[wy0:wy1, wx0:wx1] |= np.isin(wl, hit[hit > 0]).astype(np.uint8)
            # 沿笔画生长：从已取到的墨出发，逐像素并入相邻的更淡墨迹（纸色差 > GROW），
            # 最多走 GROWN 步、不出本字框，补回长笔画中段的淡墨，又不至于吃进大片纸纹
            dw = dark[wy0:wy1, wx0:wx1]
            seed = m[wy0:wy1, wx0:wx1].copy()
            allow = ((dw > GROW) & (rule[wy0:wy1, wx0:wx1] == 0)).astype(np.uint8)
            for _ in range(GROWN):
                nxt_ = cv2.dilate(seed, np.ones((3, 3), np.uint8)) & allow
                if (nxt_ | seed).sum() == seed.sum(): break
                seed |= nxt_
            m[wy0:wy1, wx0:wx1] = seed
            m = cv2.dilate(m, np.ones((3, 3), np.uint8))       # 带上笔画边缘
            # 按本字自身墨色归一化：取本字强墨纸色差的 90 分位作「满墨」，整体偏淡的字也饱满
            ref = float(np.percentile(dark[mask > 0], 90))
            a1 = max(A1MIN, ref * FULL)
            alpha = np.clip((dark - A0) / (a1 - A0), 0, 1) * m
            # 统一字身：墨迹中心对方格中心；大于方格的整体缩小
            gh, gw = gy1 - gy0, gx1 - gx0
            k = min(1.0, S * 0.94 / max(gh, gw))
            mcy, mcx = (gy0 + gy1) / 2, (gx0 + gx1) / 2
            M = np.float32([[k, 0, S / 2 - k * mcx], [0, k, S / 2 - k * mcy]])
            a = cv2.warpAffine(alpha.astype(np.float32), M, (S, S), flags=cv2.INTER_AREA)
            a = cv2.resize(a, (OUTPX, OUTPX), interpolation=cv2.INTER_CUBIC).clip(0, 1)
            rgba = np.zeros((OUTPX, OUTPX, 4), np.uint8)
            rgba[..., :3] = 17
            rgba[..., 3] = (a * 255).astype(np.uint8)
            cv2.imwrite(f"{GL}/{pid}/{it['idx']:03d}.png", rgba)
            meta['items'].append({'idx': it['idx'], 'char': it['char'], 'note': it['note'], 'col': c,
                                  'p': it['p'], 'box': [int(gx0), int(gy0), int(gw), int(gh)],
                                  'shrink': round(k, 3)})
    meta['items'].sort(key=lambda t: t['idx'])
    json.dump(meta, open(f'{GL}/{pid}/meta.json', 'w'), ensure_ascii=False, indent=1)
    print(f'{pid}: {len(meta["items"])} 字，字身 S={S}px（中位字高 {s:.0f}）-> {OUTPX}px')

if __name__ == '__main__':
    for pid in sys.argv[1:]:
        run(pid)
