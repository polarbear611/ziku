# 复核队列：只把「可能有问题」的字图交给人看
# 两个信号：① 识别概率 p（标签字在 PP-OCR 输出里的概率）
#           ② 同字一致性 cons（该字图与同标签其它样本的中位相关度，样本 ≥3 时有效）
# 等级: A 疑似错 = p<0.05 且（一致性离群或无同字样本）
#       B 低置信 = 其余 p<0.3，或 一致性离群
#       C 无法自动校验 = 字典外的字 / 夹注
# 外加整页级的「缺字」「废段」
# 用法: python qa.py  -> out3/qa.json + 统计
import json, glob, os, cv2
import numpy as np
from collections import defaultdict
import align

OUT = align.OUT3
SZ = 40

def feat(img, it):
    p = 3
    c = img[max(0, it['y'] - p):it['y'] + it['h'] + p, max(0, it['x'] - p):it['x'] + it['w'] + p]
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = g.max() - g
    h, w = g.shape
    s = max(h, w)
    sq = np.zeros((s, s), np.float32)
    sq[(s - h) // 2:(s - h) // 2 + h, (s - w) // 2:(s - w) // 2 + w] = g
    f = cv2.GaussianBlur(cv2.resize(sq, (SZ, SZ), interpolation=cv2.INTER_AREA), (5, 5), 0).ravel()
    f -= f.mean()
    return f / (np.linalg.norm(f) + 1e-6)

def main():
    items = []
    extras = {}
    for fn in sorted(glob.glob(f'{OUT}/p??.json')):
        pid = os.path.basename(fn)[:3]
        img = cv2.imread(f'{align.PAGES}/{pid}.png')
        for it in json.load(open(fn)):
            it['pid'] = pid
            it['f'] = feat(img, it)
            items.append(it)
        ex = f'{OUT}/{pid}_extra.json'
        if os.path.exists(ex):
            extras[pid] = json.load(open(ex))
    by = defaultdict(list)
    for i, it in enumerate(items):
        by[it['char']].append(i)
    for ch, idx in by.items():
        if len(idx) < 3:
            for i in idx: items[i]['cons'] = None
            continue
        F = np.stack([items[i]['f'] for i in idx])
        S = F @ F.T
        np.fill_diagonal(S, np.nan)
        med = np.nanmedian(S, 1)
        for i, m in zip(idx, med): items[i]['cons'] = round(float(m), 3)
    # 一致性离群阈：全体中位数 - 3*MAD
    cs = np.array([it['cons'] for it in items if it['cons'] is not None])
    thr = float(np.median(cs) - 3 * np.median(np.abs(cs - np.median(cs))))
    stat = defaultdict(int)
    queue = []
    # 相邻标签：识别 top1 恰好是前/后一个字 -> 典型错位信号
    pos = {(it['pid'], it['idx']): it for it in items}
    from opencc import OpenCC
    t2s = OpenCC('t2s').convert
    for it in items:
        p, c = it['p'], it['cons']
        t1, t1p = it['top'][0]
        nb = [pos.get((it['pid'], it['idx'] + d)) for d in (-1, 1)]
        shift = any(n is not None and t2s(n['char']) == t2s(t1) and t1p >= 0.3 for n in nb)
        if p is None:
            lv = 'C' if (c is None or c < 0.6) else 'ok'
        elif shift and p < 0.05:
            lv = 'A'
        elif p >= 0.3 or (c is not None and (c >= 0.75 or (c >= 0.6 and p >= 0.01))):
            lv = 'ok'
        elif p < 0.05 and t1p >= 0.2 and (c is None or c < 0.5):
            lv = 'A'
        else:
            lv = 'B'
        it['level'] = lv
        stat[lv] += 1
        del it['f']
        if lv != 'ok':
            queue.append(it)
    json.dump({'thr_cons': thr, 'items': items, 'extras': extras},
              open(f'{OUT}/qa.json', 'w'), ensure_ascii=False, indent=1)
    n = len(items)
    nd = sum(len(e['del']) for e in extras.values()); nj = sum(len(e['junk']) for e in extras.values())
    print(f'字图 {n}；一致性离群阈 {thr:.3f}')
    for k in ('ok', 'A', 'B', 'C'):
        print(f'  {k}: {stat[k]} ({stat[k]/n:.1%})')
    print(f'  缺字 {nd}，废段 {nj}')

if __name__ == '__main__':
    main()
