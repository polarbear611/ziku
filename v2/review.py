# 生成复核页 review/index.html：只列 qa.json 里 A/B/C 级的字 + 缺字/废段
# 每条给：字图（含上下文，红框为当前字）、标签、识别 top3、等级；可标「对/错/改字」，导出 corrections.json
# 用法: python qa.py && python review.py  -> 浏览器打开 v2/review/index.html
import json, os, cv2, html
import align

OUT = align.OUT3
RV = f'{align.ROOT}/v2/review'
os.makedirs(f'{RV}/img', exist_ok=True)
PAD = 4

def ctx(img, x, y, w, h, fn):
    H, W = img.shape[:2]
    m = int(max(w, h) * 1.2)
    y0, y1 = max(0, y - m), min(H, y + h + m)
    x0, x1 = max(0, x - m // 2), min(W, x + w + m // 2)
    c = img[y0:y1, x0:x1].copy()
    cv2.rectangle(c, (x - x0, y - y0), (x - x0 + w, y - y0 + h), (0, 0, 230), 2)
    s = 220 / c.shape[0]
    cv2.imwrite(f'{RV}/img/{fn}', cv2.resize(c, (max(1, int(c.shape[1] * s)), 220)))
    # 单字图：入库时实际切下的图（框外扩 PAD 像素），原尺寸保存
    sc = img[max(0, y - PAD):y + h + PAD, max(0, x - PAD):x + w + PAD]
    cv2.imwrite(f'{RV}/img/s_{fn}', sc)

def main():
    qa = json.load(open(f'{OUT}/qa.json'))
    pages = {}
    rows = []
    for it in qa['items']:
        if it['level'] == 'ok':
            continue
        pid = it['pid']
        if pid not in pages:
            pages[pid] = cv2.imread(f'{align.PAGES}/{pid}.png')
        fn = f"{pid}_{it['idx']:03d}.jpg"
        ctx(pages[pid], it['x'], it['y'], it['w'], it['h'], fn)
        rows.append({'key': f"{pid}:{it['idx']}", 'pid': pid, 'col': it['col'], 'char': it['char'],
                     'level': it['level'], 'p': it['p'], 'cons': it['cons'],
                     'top': ' '.join(f'{c}{v:.2f}' for c, v in it['top']), 'img': f'img/{fn}',
                     'single': f'img/s_{fn}', 'size': f"{it['w']}×{it['h']}", 'n': it['idx']})
    for pid, ex in qa['extras'].items():
        if pid not in pages:
            pages[pid] = cv2.imread(f'{align.PAGES}/{pid}.png')
        for k, j in enumerate(ex['junk']):
            fn = f'{pid}_junk{k}.jpg'
            ctx(pages[pid], j['x'], j['y'], j['w'], j['h'], fn)
            rows.append({'key': f'{pid}:junk{k}', 'pid': pid, 'col': j['col'], 'char': '',
                         'level': '废段', 'p': None, 'cons': None,
                         'top': ' '.join(f'{c}{v:.2f}' for c, v in j['top']), 'img': f'img/{fn}',
                         'single': f'img/s_{fn}', 'size': f"{j['w']}×{j['h']}", 'n': j['idx'] if 'idx' in j else 0})
        for d in ex['del']:
            rows.append({'key': f"{pid}:del{d['idx']}", 'pid': pid, 'col': d['col'], 'char': d['char'],
                         'level': '缺字', 'p': None, 'cons': None, 'top': '', 'img': '', 'single': '', 'size': '', 'n': d['idx']})
    # 按原帖顺序：页 → 页内字序（右列→左列、上→下）
    rows.sort(key=lambda r: (r['pid'], r['n'], r['key']))
    tpl = open(f'{align.ROOT}/v2/review_tpl.html').read()
    open(f'{RV}/index.html', 'w').write(tpl.replace('/*DATA*/[]', json.dumps(rows, ensure_ascii=False)))
    print(f'复核条目 {len(rows)} -> {RV}/index.html')

if __name__ == '__main__':
    main()
