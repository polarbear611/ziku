# 欧阳询《九成宫醴泉铭》

拓本扫描，剪裱册 48 页，每页通常 4 列 × 6 字，黑底白字。扫描图不随仓库分发。

| 文件 | 内容 |
|---|---|
| `book.json` | 元数据、检索别名 `alias`（帖上异体 → 通行字，只用于检索）、不入库清单 `drop` |
| `baseline.txt` | 通行释文，取自 [Wikisource《九成宮醴泉碑銘》](https://zh.wikisource.org/wiki/九成宮醴泉碑銘)（CC BY-SA 4.0），去掉标点和模板，保留其照碑录的异体（扵、夲、㓛 等） |
| `text/pNN.tokens` | 逐页逐列释文：`seed_text.py` 自动生成，再逐页对图人工核对 |
| `text/seed_report.txt` | 自动生成时的低分、废格、缺字记录 |

## 流程

```bash
cd v2
export ZIKU_BOOK=jcg
venv/bin/python prep_pages.py ../原贴/九成宫醴泉铭-欧阳询 1 48   # 去朱印、补纸 -> 反色 -> 拉伸去石纹 -> 缩放
venv/bin/python seed_text.py 1 48                          # 释文初稿（会覆盖 text/，人工改过的先备份）
./run_pages.sh p01 p02 …                                    # 对齐 -> 抠图 -> 矢量
```

## 人工核对记录

- 48 页全部对图核对过页、列划分，自动初稿只错一处：p47 末字「𠮷」被分到 p48，已移回 p47。
- 补纸、残损遮住的字列字数与图上不一致的，留给整页对齐判「缺字」，不手改。
- 字头按释文录（如「勑」「𠮷」），网站检索通过 `alias` 也能用通行字查到。
