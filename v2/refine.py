# 对齐后的夹注定位（align3 之后、glyph 之前）
# 夹注（双行小字）不沿列切。优先用人工框 v2/text/<pid>_notes.json {"序号": [x,y,w,h]}；
# 没有人工框时，取不属于正文字的墨块，按「右行在前、行内自上而下」聚成小字依次配给注文，并标 note_auto 进复核。
# 离散部件归属（黃的八、為的两点等）不在这里做，见 glyph.py 的 assign()：识别模型对异体字不可靠，不用它定边界。
# 用法: python refine.py p01  -> 改写 out3/<pid>.json（原件留作 <pid>_raw.json）
import cv2, json, os, shutil, sys
import numpy as np
import align

OUT3 = f'{align.ROOT}/v2/out3'

def place_notes(b, lab, st, mains, notes, axis, sw, pitch, s, log):
    """一段连续注文 -> 在其前后正文字之间、字轴以外（或正文字纵向范围以外）的墨块里找小字"""
    if not notes:
        return
    prev = [m for m in mains if m['idx'] < notes[0]['idx']]
    nxt = [m for m in mains if m['idx'] > notes[-1]['idx']]
    ylo = prev[-1]['y'] if prev else 0
    yhi = nxt[0]['y'] + nxt[0]['h'] if nxt else b.shape[0]
    xlo, xhi = int(axis - pitch / 2), int(axis + pitch / 2)
    half = 0.45 * sw
    sub = lab[ylo:yhi, xlo:xhi]
    comps = []
    for i in np.unique(sub):
        if not i: continue
        X, Y, W, H, A = st[i]
        if A < 12 or Y < ylo or Y + H > yhi: continue
        off = max(0, min(X + W, axis + half) - max(X, axis - half)) < 0.3 * W
        free = not any(m['y'] <= Y + H / 2 <= m['y'] + m['h'] for m in mains)
        if off or free:
            comps.append([X, Y, X + W, Y + H])
    if not comps:
        log.append(f"  注文 {''.join(n['char'] for n in notes)}: 未找到墨块"); return
    # 合并相近墨块成小字
    g = 0.08 * s
    merged = True
    while merged:
        merged = False
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                a, c = comps[i], comps[j]
                if a[0] - g <= c[2] and c[0] - g <= a[2] and a[1] - g <= c[3] and c[1] - g <= a[3]:
                    comps[i] = [min(a[0], c[0]), min(a[1], c[1]), max(a[2], c[2]), max(a[3], c[3])]
                    comps.pop(j); merged = True; break
            if merged: break
    # 分行：按 x 中心聚类（相差超过半个小字宽算另一行），右行在前，行内自上而下
    comps.sort(key=lambda r: -(r[0] + r[2]) / 2)
    lines = []
    for r in comps:
        cx = (r[0] + r[2]) / 2
        if lines and abs(lines[-1][0] - cx) < 0.3 * sw:
            lines[-1][1].append(r)
        else:
            lines.append([cx, [r]])
    glyphs = [r for _, rs in lines for r in sorted(rs, key=lambda r: r[1])]
    # 数量不符：多了合并纵向最近的一对（同行），少了把最高的一个从中间劈开
    while len(glyphs) > len(notes):
        k = min(range(len(glyphs) - 1), key=lambda k: abs(glyphs[k + 1][1] - glyphs[k][3]) + 1e3 * (abs((glyphs[k][0] + glyphs[k][2]) - (glyphs[k + 1][0] + glyphs[k + 1][2])) > 0.6 * sw))
        a, c = glyphs[k], glyphs[k + 1]
        glyphs[k:k + 2] = [[min(a[0], c[0]), min(a[1], c[1]), max(a[2], c[2]), max(a[3], c[3])]]
    while len(glyphs) < len(notes):
        k = max(range(len(glyphs)), key=lambda k: glyphs[k][3] - glyphs[k][1])
        a = glyphs[k]; m = (a[1] + a[3]) // 2
        glyphs[k:k + 1] = [[a[0], a[1], a[2], m], [a[0], m, a[2], a[3]]]
    for n, r in zip(notes, glyphs):
        n.update(x=int(r[0]), y=int(r[1]), w=int(r[2] - r[0]), h=int(r[3] - r[1]))
    log.append(f"  注文 {''.join(n['char'] for n in notes)}: {len(lines)} 行")

def run(pid):
    raw = f'{OUT3}/{pid}_raw.json'
    if not os.path.exists(raw):
        shutil.copy(f'{OUT3}/{pid}.json', raw)
    items = json.load(open(raw))
    img = cv2.imread(f'{align.WORK}/pages/{pid}.png')
    b = align.binarize(img)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    mains_all = [it for it in items if not it['note']]   # align3 输出里注文的框是占位的 0
    s = float(np.median([it['h'] for it in mains_all]))
    sw = float(np.median([it['w'] for it in mains_all]))
    cols = sorted({it['col'] for it in items})
    axes = {c: float(np.median([it['x'] + it['w'] / 2 for it in mains_all if it['col'] == c])) for c in cols}
    pitch = float(np.median(np.abs(np.diff([axes[c] for c in cols])))) if len(cols) > 1 else 3 * sw
    manual = {}
    mf = f'{align.ROOT}/v2/text/{pid}_notes.json'
    if os.path.exists(mf):
        manual = {int(k): v for k, v in json.load(open(mf)).items() if not k.startswith('_')}
    log = []
    for c in cols:
        its = sorted([it for it in items if it['col'] == c], key=lambda t: t['idx'])
        mains = [it for it in its if not it['note']]
        run_ = []
        for it in its + [None]:
            if it is not None and it['note']:
                if it['idx'] in manual:
                    x, y, w, h = manual[it['idx']]
                    it.update(x=x, y=y, w=w, h=h, note_src='manual')
                else:
                    run_.append(it)
                continue
            place_notes(b, lab, st, mains, run_, axes[c], sw, pitch, s, log)
            for n_ in run_: n_['note_src'] = 'auto'
            run_ = []
    json.dump(items, open(f'{OUT3}/{pid}.json', 'w'), ensure_ascii=False, indent=1)
    print(f'{pid}: 注文定位完成（人工框 {len(manual)}）')
    print('\n'.join(log))

if __name__ == '__main__':
    for pid in sys.argv[1:]:
        run(pid)
