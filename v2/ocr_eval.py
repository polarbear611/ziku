# 用 RapidOCR(PP-OCR) 单字识别做「独立裁判」：比较字图与标签是否一致（与 v1/v2 的切分都无关）
# python ocr_eval.py v1 p02  |  python ocr_eval.py v2 p02
import json, sys, os, cv2
from rapidocr_onnxruntime import RapidOCR
eng = RapidOCR()
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from opencc import OpenCC
import align
cc = OpenCC('t2s')
LIB = f'{align.ROOT}/字库/姜夔-跋王献之保母帖'

def crops(which, pid):
    if which == 'v1':
        m = json.load(open(f'{LIB}/manifest.json'))['items']
        for it in m:
            if it['page'] == int(pid[1:]) and it['role'] == 'main':
                yield it['char'], cv2.imread(f"{LIB}/{it['file']}")
    else:
        img = cv2.imread(f'{align.WORK}/pages/{pid}.png'); H, W = img.shape[:2]
        for r in json.load(open(f'{align.OUT}/{pid}.json')):
            if r['note']: continue
            p = 6
            c = img[max(0, r['y']-p):r['y']+r['h']+p, max(0, r['x']-p):r['x']+r['w']+p]
            yield r['char'], c

def ocr(c):
    g = cv2.copyMakeBorder(c, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
    r, _ = eng(g, use_det=False, use_cls=False, use_rec=True)
    return r[0][0] if r else ''

which, pids = sys.argv[1], sys.argv[2:]
tot = hit = 0
for pid in pids:
    items = list(crops(which, pid))
    outs = [ocr(c) for _, c in items]
    h = sum(1 for (ch, _), o in zip(items, outs) if o and (ch in o or cc.convert(ch) in cc.convert(o)))
    tot += len(items); hit += h
    print(f'{which} {pid}: {h}/{len(items)} = {h/len(items):.1%}')
print(f'{which} 合计: {hit}/{tot} = {hit/tot:.1%}')
