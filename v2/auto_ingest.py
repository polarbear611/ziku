# 无人值守入库（试做）：上传包 -> 自动定参数 -> 释文自动分页分列 -> 对齐抠图 -> 自动质检 -> report.json
# 用法: python auto_ingest.py <job 目录>
#   <job>/job.json  {key, author, dynasty, title, script(楷书|行书), text(全文), author_en?, source?}
#   <job>/src/      页面图，按文件名排序即页序
# 产物在 ZIKU_BOOKS_DIR（默认 v2/staging）/<key>/，结构同 v2/books/<帖>/，不进正式字库；人工确认后再挪进 v2/books/
# 和人工流程的差别：参数靠测量猜（拓本/墨迹、缩放、印色），每页每列字数靠 seed_text 全局对齐 + 按图数列，
# 坏字只按几何异常自动剔除（识别置信度分不出坏字，见 README「无人值守入库」）
import glob, json, os, re, shutil, subprocess, sys
import numpy as np

V2 = os.path.dirname(os.path.abspath(__file__))
STAGE = os.environ.get('ZIKU_BOOKS_DIR', f'{V2}/staging')
PY = sys.executable

def run(args, key):
    env = dict(os.environ, ZIKU_BOOK=key, ZIKU_BOOKS_DIR=STAGE, ZIKU_SEED_PITCH='auto')
    r = subprocess.run(args, cwd=V2, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f'{" ".join(args[:2])} 失败：{r.stderr[-600:]}')
    return r.stdout

# ---------- 在子进程里跑（要先设好 ZIKU_BOOK 才能 import align） ----------
def measure(src, n):
    """原图测：底色中位数（拓本黑底 < 110，墨迹 > 130）；warm_ink 只记录，实测分不出该用哪组印色阈值"""
    import cv2
    from PIL import Image
    fs = sorted(f for f in glob.glob(f'{src}/*') if f.lower().endswith(('.webp', '.png', '.jpg', '.jpeg', '.tif', '.tiff')))[:n]
    med, warm = [], []
    for f in fs[::max(1, len(fs) // 6)]:
        img = cv2.cvtColor(np.array(Image.open(f).convert('RGB')), cv2.COLOR_RGB2BGR)
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        med.append(float(np.median(g)))
        ink = (cv2.medianBlur(g, 61).astype(int) - g) > 28
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 50, 40), (14, 255, 255)) | cv2.inRange(hsv, (165, 50, 40), (180, 255, 255))
        warm.append(float((red[ink] > 0).mean()) if ink.any() else 0.0)
    return {'median_gray': float(np.median(med)), 'warm_ink': float(np.median(warm))}

def columns(pages):
    """预处理后的页：列距、每页列数、每列墨迹高度"""
    import cv2, align
    from scipy.signal import find_peaks
    out = {}
    for pid in pages:
        b = align.binarize(cv2.imread(f'{align.PAGES}/{pid}.png'))
        H, W = b.shape
        prof = align.smooth(b.sum(0).astype(float), 31)
        pk, _ = find_peaks(prof, distance=40, prominence=prof.max() * 0.08)
        pk = np.sort(pk)
        pitch = float(np.median(np.diff(pk))) if len(pk) > 1 else float(W)
        # 列峰之间太近的（同一列的左右偏旁）合并：间距 < 0.55 个列距
        keep = [pk[0]] if len(pk) else []
        for x in pk[1:]:
            if x - keep[-1] < pitch * 0.55: keep[-1] = (keep[-1] + x) // 2
            else: keep.append(x)
        keep = keep[::-1]                                   # 右 -> 左
        hs = []
        for x in keep:
            x0, x1 = int(max(0, x - pitch * 0.45)), int(min(W, x + pitch * 0.45))
            rows = np.where(b[:, x0:x1].sum(1) > 1)[0]
            hs.append(int(rows[-1] - rows[0]) if len(rows) else 0)
        out[pid] = {'pitch': pitch, 'heights': hs}
    return out

# ---------- 主流程 ----------
def ingest(job):
    J = json.load(open(f'{job}/job.json'))
    key, src = J['key'], f'{job}/src'
    assert re.fullmatch(r'[a-z0-9_-]{2,40}', key), 'key 只能是小写字母数字'
    bd = f'{STAGE}/{key}'
    if os.path.exists(bd): shutil.rmtree(bd)
    os.makedirs(f'{bd}/text')
    fs = sorted(f for f in glob.glob(f'{src}/*') if f.lower().endswith(('.webp', '.png', '.jpg', '.jpeg', '.tif', '.tiff')))
    n = len(fs)
    text = ''.join(c for c in J['text'] if '㐀' <= c <= '鿿' or '\U00020000' <= c <= '\U0002ffff' or '豈' <= c <= '﫿' or c == '々')
    open(f'{bd}/baseline.txt', 'w').write(text + '\n')
    conf = {k: J[k] for k in ('key', 'author', 'author_en', 'dynasty', 'title', 'script', 'source') if k in J}
    conf.update({'dir': f"{J['author']}-{J['title']}", 'skip': ['々'], 'alias': {}, 'frame_line': 400, 'auto': True})
    json.dump(conf, open(f'{bd}/book.json', 'w'), ensure_ascii=False, indent=1)
    # 1. 拓本/墨迹、印色
    m = json.loads(run([PY, __file__, '--measure', src, str(n)], key))
    rubbing = m['median_gray'] < 110
    conf['rubbing'] = rubbing
    if not rubbing:                                       # 墨迹：只认又红又亮的印泥，暖色墨不误伤；不按外接矩形整块涂（霉点、压字的印）
        conf['red'] = {'h': 14, 's': 80, 'v': 150}
        conf['seal_box'] = False
    # 2. 缩放：先按 1.0 预处理测列距，再缩到列距约 170px
    conf['scale'] = 1.0
    json.dump(conf, open(f'{bd}/book.json', 'w'), ensure_ascii=False, indent=1)
    pids = [f'p{i:02d}' for i in range(1, n + 1)]
    run([PY, 'prep_pages.py', src, '1', str(n)], key)
    col = json.loads(run([PY, __file__, '--columns'] + pids[::max(1, n // 6)], key))
    pitch = float(np.median([c['pitch'] for c in col.values()]))
    conf['scale'] = round(float(np.clip(170 / pitch, 0.3, 2.5)), 2)
    json.dump(conf, open(f'{bd}/book.json', 'w'), ensure_ascii=False, indent=1)
    run([PY, 'prep_pages.py', src, '1', str(n)], key)
    # 3. 释文分页（seed_text 全局对齐），每页按图数列、按列墨迹高度分配字数
    seed = run([PY, 'seed_text.py', '1', str(n)], key).strip()
    col = json.loads(run([PY, __file__, '--columns'] + pids, key))
    ncol = [len([h for h in col[p]['heights'] if h > 0]) for p in pids]
    med = int(np.median([n for n in ncol if n])) if any(ncol) else 1
    for pid in pids:
        f = f'{bd}/text/{pid}.tokens'
        chars = open(f).read().split() if os.path.exists(f) else []
        hs = [h for h in col[pid]['heights'] if h > 0]
        if not chars or not hs:
            open(f, 'w').write('-\n'); continue
        if len(hs) > med:                                  # 比全书多数页多出列：多半是石花、界线被当成列，按常见列数均分
            hs = [1] * med
        hs = hs[:len(chars)]
        cut = np.round(np.cumsum([0] + hs) / sum(hs) * len(chars)).astype(int)
        open(f, 'w').write('\n'.join(' '.join(chars[cut[i]:cut[i + 1]]) or '-' for i in range(len(hs))) + '\n')
    # 4. 对齐 -> 抠图 -> 矢量
    res = subprocess.run(['./run_pages.sh'] + pids, cwd=V2, env=dict(os.environ, ZIKU_BOOK=key, ZIKU_BOOKS_DIR=STAGE),
                         capture_output=True, text=True).stdout
    failed = [l.split()[0] for l in res.splitlines() if 'FAIL' in l]
    # 5. 自动质检：几何异常的剔除（字框高 > 1.7 倍、宽 > 1.6 倍本页中位数，或高宽都 < 0.35 倍）
    total, drop, miss = 0, [], 0
    for pid in pids:
        lg = f'{bd}/out3/{pid}.log'
        if os.path.exists(lg): miss += open(lg).read().count('缺字(文字有图上无)')
        mf = f'{bd}/glyph/{pid}/meta.json'
        if not os.path.exists(mf): continue
        its = json.load(open(mf))['items']
        if not its: continue
        H = np.median([it['box'][3] for it in its]); W = np.median([it['box'][2] for it in its])
        for it in its:
            total += 1
            h, w = it['box'][3] / H, it['box'][2] / W
            if h > 1.7 or w > 1.6 or (h < 0.35 and w < 0.35):
                drop.append([pid, it['idx']])
    conf['drop'] = drop
    json.dump(conf, open(f'{bd}/book.json', 'w'), ensure_ascii=False, indent=1)
    rep = {'key': key, 'pages': n, 'text_chars': len(text), 'glyphs': total, 'missing': miss, 'auto_drop': len(drop),
           'failed_pages': failed, 'seed': seed, 'measure': m, 'scale': conf['scale'], 'rubbing': rubbing,
           'red': conf.get('red', 'default')}
    rate = (len(text) - total + len(failed)) / max(1, len(text))
    mt = re.search(r'对上 (\d+)', seed)
    rep['seed_match'] = round(int(mt.group(1)) / max(1, len(text)), 3) if mt else 0
    # 字图数凑够了不代表对：雁塔圣教序自动版字数齐全但大面积错位，seed 全局对齐只对上 64%（多宝塔 91%、赤壁赋 99%）
    rep['status'] = 'review' if not failed and rate < 0.05 and rep['seed_match'] >= 0.85 else 'needs_human'
    json.dump(rep, open(f'{bd}/report.json', 'w'), ensure_ascii=False, indent=1)
    return rep

if __name__ == '__main__':
    if sys.argv[1] == '--measure':
        print(json.dumps(measure(sys.argv[2], int(sys.argv[3]))))
    elif sys.argv[1] == '--columns':
        print(json.dumps(columns(sys.argv[2:])))
    else:
        print(json.dumps(ingest(sys.argv[1]), ensure_ascii=False, indent=1))
