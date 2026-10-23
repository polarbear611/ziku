# 扫描 PDF -> 逐页 PNG（流水线的输入 work/pages/pNN.png，宽 2000px）
# 扫描图不随仓库分发，需自备；第 N 页对应 PDF 的第 N 页。
# 用法: python prep_pages.py <扫描.pdf> [起始页 结束页]   默认 1 18
import os, sys
import pymupdf
import align

def main():
    pdf = sys.argv[1]
    a, b = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1, 18)
    out = f'{align.WORK}/pages'
    os.makedirs(out, exist_ok=True)
    doc = pymupdf.open(pdf)
    for n in range(a, b + 1):
        page = doc[n - 1]
        z = 2000 / page.rect.width
        page.get_pixmap(matrix=pymupdf.Matrix(z, z)).save(f'{out}/p{n:02d}.png')
    print(f'{b - a + 1} 页 -> {out}')

if __name__ == '__main__':
    main()
