# 对齐结果拼图：python sheet.py p02 -> out/p02_sheet.png（字图上方标 字+序号）
import json, sys, cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import align
pid = sys.argv[1]
OUTD = sys.argv[2] if len(sys.argv) > 2 else align.OUT
res = json.load(open(f'{OUTD}/{pid}.json'))
img = cv2.cvtColor(cv2.imread(f'{align.WORK}/pages/{pid}.png'), cv2.COLOR_BGR2RGB)
H, W = img.shape[:2]
font = ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc', 22)
C, T = 12, 90
rows = (len(res) + C - 1) // C
sh = Image.new('RGB', (C * T, rows * (T + 26)), 'white'); d = ImageDraw.Draw(sh)
for k, r in enumerate(res):
    p = 5
    y0, y1 = max(0, r['y'] - p), min(H, r['y'] + r['h'] + p)
    x0, x1 = max(0, r['x'] - p), min(W, r['x'] + r['w'] + p)
    c = img[y0:y1, x0:x1]
    s = max(c.shape[:2]); sq = np.full((s, s, 3), 200, np.uint8)
    sq[(s - c.shape[0]) // 2:(s - c.shape[0]) // 2 + c.shape[0], (s - c.shape[1]) // 2:(s - c.shape[1]) // 2 + c.shape[1]] = c
    x = (k % C) * T; y = (k // C) * (T + 26)
    sh.paste(Image.fromarray(sq).resize((T, T)), (x, y + 26))
    d.text((x + 4, y), f"{r['char']}{k}", fill='red' if r['note'] else 'blue', font=font)
sh.save(f'{OUTD}/{pid}_sheet.png')
