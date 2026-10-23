# 矢量化：glyph/<pid>/<idx>.png 的 alpha -> potrace 贝塞尔轮廓 -> <idx>.svg（透明底、单色填充）
# 再生成预览页 glyph/<pid>/index.html：米字格里并排看「原图 / 透明位图 / 矢量」
# 用法: python vector.py p01
import cv2, json, sys, html
import numpy as np
import potrace
import align

GL = align.GL
TH = 0.35          # alpha 阈值：低于它的淡墨不进轮廓
BLUR = 1.2         # 描轮廓前的高斯平滑（256 图上的像素）
TURD = 15          # 面积小于此（像素，256 图上）的斑点丢弃

def trace(alpha):
    bm = potrace.Bitmap(alpha < TH)      # potracer 把 False 当作前景
    paths = bm.trace(turdsize=TURD, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
                     alphamax=1.0, opticurve=True, opttolerance=0.2)
    d = []
    for cv in paths:
        f = lambda p: f'{p.x:.1f} {p.y:.1f}'
        d.append('M' + f(cv.start_point))
        for sg in cv.segments:
            if sg.is_corner:
                d.append(f'L{f(sg.c)}L{f(sg.end_point)}')
            else:
                d.append(f'C{f(sg.c1)} {f(sg.c2)} {f(sg.end_point)}')
        d.append('Z')
    return ''.join(d)

def run(pid):
    meta = json.load(open(f'{GL}/{pid}/meta.json'))
    img = cv2.imread(f'{align.PAGES}/{pid}.png')
    N = None
    for it in meta['items']:
        fn = f"{GL}/{pid}/{it['idx']:03d}"
        a = cv2.imread(fn + '.png', cv2.IMREAD_UNCHANGED)[..., 3].astype(np.float32) / 255
        a = cv2.GaussianBlur(a, (0, 0), BLUR)            # 轻度平滑：接上笔画里的细小断口、轮廓更顺
        N = a.shape[0]
        d = trace(a)
        open(fn + '.svg', 'w').write(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {N} {N}">'
            f'<path fill="#111" fill-rule="evenodd" d="{d}"/></svg>')
        it['d'] = d
        # 原图（同一字身框，供对照）
        x, y, w, h = it['box']
        S = meta['S']
        cx, cy = x + w / 2, y + h / 2
        c = img[max(0, int(cy - S / 2)):int(cy + S / 2), max(0, int(cx - S / 2)):int(cx + S / 2)]
        cv2.imwrite(fn + '_src.jpg', cv2.resize(c, (128, 128)))
    rows = [{k: it[k] for k in ('idx', 'char', 'note', 'p', 'd', 'shrink')} for it in meta['items']]
    tpl = open(f'{align.ROOT}/v2/glyph_tpl.html').read()
    out = tpl.replace('/*PID*/', pid).replace('/*N*/0', str(N)).replace('/*DATA*/[]', json.dumps(rows, ensure_ascii=False))
    open(f'{GL}/{pid}/index.html', 'w').write(out)
    print(f'{pid}: {len(rows)} 个 SVG -> {GL}/{pid}/index.html')

if __name__ == '__main__':
    for pid in sys.argv[1:]:
        run(pid)
