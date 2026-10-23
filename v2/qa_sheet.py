# 复核等级拼图：python qa_sheet.py A out3/qa_A.png
import json, sys, cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import align
lv, out = sys.argv[1], sys.argv[2]
q = json.load(open(f'{align.OUT3}/qa.json'))
its = [i for i in q['items'] if i['level'] == lv]
font = ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc', 18)
C, T = 10, 100
sh = Image.new('RGB', (C * T, ((len(its) + C - 1) // C) * (T + 40)), 'white'); d = ImageDraw.Draw(sh)
pages = {}
for k, it in enumerate(its):
    if it['pid'] not in pages:
        pages[it['pid']] = cv2.cvtColor(cv2.imread(f"{align.PAGES}/{it['pid']}.png"), cv2.COLOR_BGR2RGB)
    img = pages[it['pid']]; p = 5
    c = img[max(0, it['y'] - p):it['y'] + it['h'] + p, max(0, it['x'] - p):it['x'] + it['w'] + p]
    s = max(c.shape[:2]); sq = np.full((s, s, 3), 200, np.uint8)
    sq[(s - c.shape[0]) // 2:(s - c.shape[0]) // 2 + c.shape[0], (s - c.shape[1]) // 2:(s - c.shape[1]) // 2 + c.shape[1]] = c
    x = (k % C) * T; y = (k // C) * (T + 40)
    sh.paste(Image.fromarray(sq).resize((T, T)), (x, y + 40))
    d.text((x + 2, y), f"{it['char']} {it['pid']}:{it['idx']}", fill='blue', font=font)
    d.text((x + 2, y + 19), f"→{it['top'][0][0]}{it['top'][0][1]:.2f}", fill='red', font=font)
sh.save(out)
print(len(its))
