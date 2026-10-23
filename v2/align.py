# v2 字-格强制对齐：已知每列文字 -> 在该列 y 方向 DP 求最优切点
# 与 v1 的区别：不再「先盲切再人工配 token」，而是用文字（字数 + 每字预期高度）驱动切分，
# 一列内不会因为某个字被切碎/粘连而整体错位。
# 用法: python align.py p02 [p03 ...]   -> out/<pid>.json + out/<pid>_ov.jpg
import cv2, json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = f'{ROOT}/work'
OUT = f'{ROOT}/v2/out'
os.makedirs(OUT, exist_ok=True)
# 多部字帖：环境变量 ZIKU_BOOK 选帖（v2/books/<帖>/book.json），默认姜夔《保母帖》。
# 保母帖沿用最早的目录（work/pages、v2/text、v2/out3、v2/glyph），新帖的数据都放在 v2/books/<帖>/ 下
BOOK = os.environ.get('ZIKU_BOOK', 'baomu')
BOOKDIR = f'{ROOT}/v2/books/{BOOK}'
CONF = json.load(open(f'{BOOKDIR}/book.json'))
if BOOK == 'baomu':
    PAGES, TEXT, TOKENS = f'{WORK}/pages', f'{ROOT}/v2/text', f'{WORK}/tokens'
    OUT3, GL = f'{ROOT}/v2/out3', f'{ROOT}/v2/glyph'
else:
    PAGES, TEXT, TOKENS = f'{BOOKDIR}/pages', f'{BOOKDIR}/text', None
    OUT3, GL = f'{BOOKDIR}/out3', f'{BOOKDIR}/glyph'
FONT = os.environ.get('ZIKU_FONT', '/System/Library/Fonts/Supplemental/Songti.ttc')   # 宋体，用于估字高；非 macOS 用环境变量指定
STEP = 3

# ---------- 文字 ----------
def column_texts(pid):
    """tokens 每行 -> [(字, is_note)]，去掉 -、@2、% 等 v1 的格标记
    v2/text/<pid>.tokens 存在时优先用它（v2 自己的释文修正，不改 work/ 下的原件）"""
    cols = []
    fix = f'{TEXT}/{pid}.tokens'
    for line in open(fix if os.path.exists(fix) or not TOKENS else f'{TOKENS}/{pid}.tokens'):
        if not line.strip():
            continue
        seq = []
        for t in line.split():
            t = t.replace('@2', '').replace('%', '')
            note = t.startswith('^')
            t = t.lstrip('^')
            if t == '-' or not t:
                continue
            seq += [(c, note) for c in t]
        cols.append(seq)
    return cols

_hcache = {}
_font = ImageFont.truetype(FONT, 100)
def glyph_ratio(ch):
    """字形紧包围盒高/宽 占字身比例（宋体），作预期高度先验"""
    if ch not in _hcache:
        im = Image.new('L', (140, 140), 0)
        ImageDraw.Draw(im).text((20, 10), ch, fill=255, font=_font)
        a = np.array(im) > 80
        ys, xs = np.where(a)
        if len(ys) == 0:
            _hcache[ch] = (0.8, 0.8)
        else:
            _hcache[ch] = ((ys.max() - ys.min() + 1) / 100, (xs.max() - xs.min() + 1) / 100)
    return _hcache[ch]

# ---------- 图像 ----------
def red_mask(img):
    """朱印、红栏"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 50, 40), (14, 255, 255)) | cv2.inRange(hsv, (165, 50, 40), (180, 255, 255))
    return cv2.dilate(red, np.ones((5, 5), np.uint8))

def binarize(img):
    H, W = img.shape[:2]
    red = red_mask(img)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.inpaint(g, red, 5, cv2.INPAINT_TELEA).astype(np.float32)
    bg = cv2.medianBlur(g.astype(np.uint8), 61).astype(np.float32)   # 局部纸色，抗污渍/明暗不匀
    b = ((bg - g) > 28).astype(np.uint8)
    b[red > 0] = 0
    # 去小斑点
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 25
    b = keep[lab].astype(np.uint8)
    # 去外框线：贴边长线
    for k, ax in (((120, 1), 1), ((1, 120), 0)):
        ln = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        b[cv2.dilate(ln, np.ones((5, 5), np.uint8)) > 0] = 0
    return b

def smooth(x, k):
    k = max(1, int(k) | 1)
    return np.convolve(x, np.ones(k) / k, mode='same')

def find_columns(b, n):
    """x 投影找 n 个列带，返回 [(x0,x1)] 右->左。列距约 200px（2000 宽页），峰间距下限取 100"""
    from scipy.signal import find_peaks
    H, W = b.shape
    prof = smooth(b.sum(0).astype(float), 31)
    pk, pr = find_peaks(prof, distance=100, prominence=prof.max() * 0.05)
    if len(pk) < n:
        raise RuntimeError(f'列峰 {len(pk)} < {n}')
    pk = np.sort(pk[np.argsort(pr['prominences'])[-n:]])
    pitch = float(np.median(np.diff(pk))) if n > 1 else 200.0
    mids = [(pk[i] + pk[i + 1]) // 2 for i in range(n - 1)]
    edges = [int(max(0, pk[0] - pitch / 2))] + [int(m) for m in mids] + [int(min(W, pk[-1] + pitch / 2))]
    return [(edges[i], edges[i + 1]) for i in range(n)][::-1]

# ---------- DP ----------
def align_column(b, x0, x1, seq):
    """返回每字 (y0,y1) 及代价分解"""
    col = b[:, x0:x1]
    prof = col.sum(1).astype(float)
    ink = prof > 1
    H = len(prof)
    nz = np.where(ink)[0]
    if len(nz) == 0:
        return None
    Y0, Y1 = int(nz[0]), int(nz[-1]) + 1
    # 首尾孤立墨团（页框角、污渍）：与主体间隔超过一个字距且自身不足一个字高 -> 剔除
    N0 = len(seq)
    while True:
        pitch = (Y1 - Y0) / max(N0, 1)
        runs = np.split(nz, np.where(np.diff(nz) > 1)[0] + 1)
        if len(runs) < 2:
            break
        g_head = runs[1][0] - runs[0][-1]
        g_tail = runs[-1][0] - runs[-2][-1]
        if g_head > pitch * 1.3 and runs[0][-1] - runs[0][0] < pitch * 0.7:
            ink[runs[0]] = False
        elif g_tail > pitch * 1.3 and runs[-1][-1] - runs[-1][0] < pitch * 0.7:
            ink[runs[-1]] = False
        else:
            break
        prof = np.where(ink, prof, 0)
        nz = np.where(ink)[0]
        Y0, Y1 = int(nz[0]), int(nz[-1]) + 1
    pos = np.arange(Y0, Y1 + STEP, STEP).clip(Y0, Y1)
    P = len(pos)
    # nxt/prv 墨行
    nxt = np.full(H + 1, H, int); prv = np.full(H + 1, -1, int)
    last = H
    for y in range(H - 1, -1, -1):
        if ink[y]: last = y
        nxt[y] = last
    last = -1
    for y in range(H):
        if ink[y]: last = y
        prv[y] = last
    cp = np.concatenate([[0], np.cumsum(prof)])
    ps = smooth(prof, 5)
    rowink = np.median(prof[ink]) if ink.any() else 1
    cutc = ps[np.minimum(pos, H - 1)] / rowink    # 切在墨上的代价（墨迹到页底时 pos 可等于 H）
    N = len(seq)
    r = np.array([glyph_ratio(c)[0] * (0.55 if note else 1.0) for c, note in seq])
    span = Y1 - Y0
    s = span / (r.sum() * 1.18)

    def solve(s):
        maxlen = int(np.ceil(max(r.max() * s * 2.2, span / N * 2.5) / STEP))
        INF = 1e18
        D = np.full((N + 1, P), INF); B = np.zeros((N + 1, P), int)
        # 起点：跳过前段墨的代价
        D[0] = 3.0 * (cp[pos] - cp[Y0]) / (rowink * 20) + cutc
        for k in range(1, N + 1):
            e = s * r[k - 1]
            for j in range(1, P):
                i0 = max(0, j - maxlen)
                ii = np.arange(i0, j)
                prev = D[k - 1, ii]
                if not np.isfinite(prev).any() or prev.min() >= INF:
                    continue
                a = pos[ii]; bb = pos[j]
                t0 = nxt[a]; t1 = prv[bb - 1] if bb > 0 else -1
                h = (t1 - t0 + 1).astype(float)
                hc = np.where(h > 2, h, 2.0)
                seg = 2.0 * np.log(hc / e) ** 2
                seg = np.where(h > 2, seg, 25.0)        # 空格子重罚
                c = prev + seg + cutc[j] * 1.5
                m = int(np.argmin(c))
                D[k, j] = c[m]; B[k, j] = ii[m]
        # 终点：跳过尾段墨
        tail = 3.0 * (cp[Y1] - cp[pos]) / (rowink * 20)
        j = int(np.argmin(D[N] + tail))
        cuts = [j]
        for k in range(N, 0, -1):
            j = B[k, j]; cuts.append(j)
        cuts = [int(pos[c]) for c in cuts[::-1]]
        segs = []
        for k in range(N):
            a, bb = cuts[k], cuts[k + 1]
            t0, t1 = int(nxt[a]), int(prv[bb - 1])
            segs.append((a, bb, t0, t1))
        return segs, float(D[N].min())

    for _ in range(3):
        segs, cost = solve(s)
        hs = np.array([max(2, t1 - t0 + 1) for _, _, t0, t1 in segs])
        s = float(np.median(hs / (r * 1.0)))
    segs, cost = solve(s)
    return segs, s

def char_box(b, x0, x1, t0, t1):
    """在 [t0,t1] 行内求墨的 x 范围（可越出列带一点）"""
    sub = b[t0:t1 + 1, x0:x1]
    cs = sub.sum(0)
    xs = np.where(cs > 0)[0]
    if len(xs) == 0:
        return x0, x1
    # 按 ≤8px 的空隙合并成墨团，只保留占总墨量 ≥12% 的团（去掉边上的斑点和邻列笔画尖）
    runs = np.split(xs, np.where(np.diff(xs) > 8)[0] + 1)
    tot = cs.sum()
    big = [r for r in runs if cs[r].sum() >= 0.12 * tot] or [max(runs, key=lambda r: cs[r].sum())]
    return x0 + int(big[0][0]), x0 + int(big[-1][-1]) + 1

def run(pid):
    img = cv2.imread(f'{PAGES}/{pid}.png')
    b = binarize(img)
    texts = column_texts(pid)
    cols = find_columns(b, len(texts))
    res = []
    ov = img.copy()
    for ci, ((x0, x1), seq) in enumerate(zip(cols, texts)):
        out = align_column(b, x0, x1, seq)
        segs, s = out
        cv2.rectangle(ov, (x0, 0), (x1, img.shape[0] - 1), (255, 0, 0), 1)
        for k, ((a, bb, t0, t1), (ch, note)) in enumerate(zip(segs, seq)):
            cx0, cx1 = char_box(b, x0, x1, t0, t1)
            res.append({'col': ci, 'k': k, 'char': ch, 'note': note,
                        'x': cx0, 'y': t0, 'w': cx1 - cx0, 'h': t1 - t0 + 1,
                        'cut0': a, 'cut1': bb})
            cv2.rectangle(ov, (cx0, t0), (cx1, t1), (0, 160, 0) if not note else (0, 120, 255), 2)
            cv2.line(ov, (x0, a), (x1, a), (0, 0, 255), 1)
        print(f'{pid} 列{ci} x=({x0},{x1}) 字数={len(seq)} 尺度={s:.0f}')
    json.dump(res, open(f'{OUT}/{pid}.json', 'w'), ensure_ascii=False, indent=1)
    cv2.imwrite(f'{OUT}/{pid}_ov.jpg', cv2.resize(ov, (1000, int(ov.shape[0] * 1000 / ov.shape[1]))))
    cv2.imwrite(f'{OUT}/{pid}_bin.png', cv2.resize(b * 255, (1000, int(b.shape[0] * 1000 / b.shape[1])), interpolation=cv2.INTER_AREA))
    return res

if __name__ == '__main__':
    for pid in sys.argv[1:]:
        run(pid)
