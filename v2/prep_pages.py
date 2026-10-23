# 扫描源 -> 逐页 PNG（流水线的输入；保母帖在 work/pages/，其它帖在 v2/books/<帖>/pages/）
# 扫描图不随仓库分发，需自备。源可以是 PDF（第 N 页 = PDF 第 N 页），也可以是图片目录（按文件名排序，第 N 张 = 第 N 页）
# 拓本（book.json 里 "rubbing": true，黑底白字）：去朱印、去补纸 -> 反色成白底黑字 -> 缩放到字高约 100px，
# 之后的对齐、抠图与墨迹本完全相同
# book.json 可选：crops（单张长图按矩形裁成多页）、mask（逐页要涂掉的矩形，源图坐标）
# 用法: ZIKU_BOOK=jcg python prep_pages.py <扫描.pdf | 图片目录 | 单张长图> [起始页 结束页]
import glob, os, sys
import cv2
import numpy as np
import pymupdf
from PIL import Image
import align

def load(src, n):
    crops = align.CONF.get('crops')           # 单张长图拼了多段：按 book.json 的 [x0,y0,x1,y1] 裁出第 N 页
    if crops and os.path.isfile(src):
        x0, y0, x1, y1 = crops[n - 1]
        return cv2.cvtColor(np.array(Image.open(src).convert('RGB')), cv2.COLOR_RGB2BGR)[y0:y1, x0:x1].copy()
    if os.path.isdir(src):
        fs = sorted(f for f in glob.glob(f'{src}/*') if f.lower().endswith(('.webp', '.png', '.jpg', '.jpeg', '.tif', '.tiff')))
        return cv2.cvtColor(np.array(Image.open(fs[n - 1]).convert('RGB')), cv2.COLOR_RGB2BGR)
    page = pymupdf.open(src)[n - 1]
    z = 2000 / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z))
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3][:, :, ::-1].copy()

def rubbing(img, scale):
    """拓本 -> 白底黑字。朱印按外接矩形整块抹掉（印文常有白底）；补纸 = 大于笔画宽度的成片亮区"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 110, 80), (12, 255, 255)) | cv2.inRange(hsv, (165, 110, 80), (180, 255, 255))
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    seal = np.zeros(red.shape, np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(red, 8)
    for X, Y, W, H, A in st[1:]:
        if A >= 400:
            cv2.rectangle(seal, (X - 6, Y - 6), (X + W + 6, Y + H + 6), 1, -1)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    op = cv2.morphologyEx(g, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45)))
    patch = cv2.dilate((op > 95).astype(np.uint8), np.ones((15, 15), np.uint8))
    inv = 255 - g
    inv[(seal > 0) | (patch > 0)] = 255
    inv = cv2.resize(inv, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale <= 1 else cv2.INTER_CUBIC)
    # 石面纹理：按局部底色拉伸，比底色深不到 50 的一律当白（否则二值化后满版噪点，字框被撑宽）
    g2 = inv.astype(np.float32)
    dark = cv2.medianBlur(inv, 61).astype(np.float32) - g2
    inv = (255 - np.clip((dark - 50) / 70, 0, 1) * 255).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats((inv < 128).astype(np.uint8), 8)
    inv[(st[lab, cv2.CC_STAT_AREA] < 20) & (lab > 0)] = 255                     # 碎斑点
    inv = cv2.copyMakeBorder(inv, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)   # 白边：墨迹不贴页边
    return cv2.cvtColor(inv, cv2.COLOR_GRAY2BGR)

def main():
    src = sys.argv[1]
    a, b = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1, 18)
    os.makedirs(align.PAGES, exist_ok=True)
    for n in range(a, b + 1):
        img = load(src, n)
        fill = 0 if align.CONF.get('rubbing') else np.median(img.reshape(-1, 3), 0)   # 墨迹本涂纸色：涂白会在边上二值化出假墨
        for x0, y0, x1, y1 in align.CONF.get('mask', {}).get(f'p{n:02d}', []):   # 不收的题签、残印、水印、邻图半列
            img[y0:y1, x0:x1] = fill
        if align.CONF.get('rubbing'):
            img = rubbing(img, align.CONF.get('scale', 1.0))
        elif align.CONF.get('scale', 1.0) != 1.0:                                 # 墨迹本只缩放（列距约 200px）
            img = cv2.resize(img, None, fx=align.CONF['scale'], fy=align.CONF['scale'], interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(f'{align.PAGES}/p{n:02d}.png', img)
    print(f'{b - a + 1} 页 -> {align.PAGES}')

if __name__ == '__main__':
    main()
