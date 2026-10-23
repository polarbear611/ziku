# PP-OCRv4 识别模型（RapidOCR 自带 onnx）当「单字打分器」：给定字图，返回指定字的概率
# 不取识别结果字符串，而是读 CTC 输出里目标字（繁/简任一）的最大帧概率
import cv2
import numpy as np
from opencc import OpenCC
from rapidocr_onnxruntime import RapidOCR

_eng = RapidOCR()
_rec = _eng.text_rec
_chars = _rec.postprocess_op.character          # 含 blank
_idx = {c: i for i, c in enumerate(_chars)}
_t2s = OpenCC('t2s')
H_IN, W_IN = 48, 96

def char_ids(ch):
    ids = {_idx[c] for c in {ch, _t2s.convert(ch)} if c in _idx}
    return sorted(ids)

def known(ch):
    return bool(char_ids(ch))

def _prep(img):
    h, w = img.shape[:2]
    pad = int(max(h, w) * 0.12) + 2
    img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    h, w = img.shape[:2]
    sc = H_IN / h
    nw = min(W_IN, max(8, int(round(w * sc))))
    r = cv2.resize(img, (nw, H_IN)).astype(np.float32).transpose(2, 0, 1) / 255
    r = (r - 0.5) / 0.5
    out = np.zeros((3, H_IN, W_IN), np.float32)
    out[:, :, :nw] = r
    return out

def probs(imgs, batch=64):
    """imgs: BGR 字图列表 -> (n, C) 每类在所有时间帧上的最大概率"""
    res = []
    for b in range(0, len(imgs), batch):
        x = np.stack([_prep(i) for i in imgs[b:b + batch]])
        p = _rec.session(x)[0]                    # (B, T, C) softmax
        res.append(p.max(axis=1))
    return np.concatenate(res) if res else np.zeros((0, len(_chars)))

def score(pvec, ch):
    ids = char_ids(ch)
    return float(max(pvec[i] for i in ids)) if ids else None

def top(pvec, k=3):
    o = np.argsort(-pvec[1:])[:k] + 1
    return [(_chars[i], round(float(pvec[i]), 3)) for i in o]
