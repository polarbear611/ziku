# 汇总各页单字成品图 -> 字库 + 网站数据（格式与 v1 的 manifest.json / index.json / 网站/db.js 一致）
# 输出到暂存目录 v2/site/，可直接作为静态站点部署
#   site/index.html                     页面（引用 网站/db.js）
#   site/网站/{index.html, db.js}        同一页面的另一份拷贝（引用 db.js）
#   site/<作品>/manifest.json, index.json, index_simplified.json
#   site/<作品>/glyphs/pNN_IIII.{png,svg}  透明底 PNG + 矢量 SVG（新目录名，避开线上 png 的 30 天缓存）
# 用法: python build_site.py
import json, os, glob, shutil, time
from opencc import OpenCC
import align

GL = f'{align.ROOT}/v2/glyph'
SITE = f'{align.ROOT}/v2/site'
WORK_DIR = '姜夔-跋王献之保母帖'
SKIP = {'々'}                       # 重文符号等，不入库
DROP = {('p05', 51), ('p05', 52)}   # 原帖磨损几乎不可见的字（令、芝），不入库

def main():
    t2s = OpenCC('t2s').convert
    lib = f'{SITE}/{WORK_DIR}'
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(f'{lib}/glyphs'); os.makedirs(f'{SITE}/网站')
    items = []
    for mf in sorted(glob.glob(f'{GL}/p??/meta.json')):
        pid = os.path.basename(os.path.dirname(mf))
        for it in json.load(open(mf))['items']:
            if it['char'] in SKIP or (pid, it['idx']) in DROP:
                continue
            gid = f"{pid}_{it['idx']:04d}"
            for ext in ('png', 'svg'):
                shutil.copy(f"{GL}/{pid}/{it['idx']:03d}.{ext}", f'{lib}/glyphs/{gid}.{ext}')
            items.append({'id': gid, 'char': it['char'], 'role': 'note' if it['note'] else 'main',
                          'page': int(pid[1:]), 'col_from_right': it['col'], 'box': it['box'],
                          'p': it['p'], 'file': f'glyphs/{gid}.png', 'svg': f'glyphs/{gid}.svg'})
    main_items = [it for it in items if it['role'] == 'main']
    # 同字多图：识别置信度高的排前（生成字帖默认取第一张）
    order = sorted(main_items, key=lambda it: (-(it['p'] if it['p'] is not None else -1), it['id']))
    idxT, idxS = {}, {}
    for it in order:
        e = {'id': it['id'], 'file': it['file'], 'page': it['page']}
        idxT.setdefault(it['char'], []).append(e)
        idxS.setdefault(t2s(it['char']), []).append(e)
    manifest = {'author': '姜夔', 'author_en': 'Jiang Kui', 'work': '跋王献之保母帖', 'dynasty': '南宋',
                'source': '故宫博物院藏本', 'pipeline': 'v2（文字驱动对齐 + 墨块归属 + 透明底/矢量）',
                'built': time.strftime('%Y-%m-%d %H:%M'), 'items': items}
    json.dump(manifest, open(f'{lib}/manifest.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(idxT, open(f'{lib}/index.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(idxS, open(f'{lib}/index_simplified.json', 'w'), ensure_ascii=False, indent=1)
    db = {'authors': [{'name': '姜夔', 'dynasty': '南宋', 'works': [{
        'key': 'jiangkui-baomutie', 'title': '跋王献之保母帖', 'count': len(main_items),
        'items': [{'id': it['id'], 'ch': it['char'], 'page': it['page'],
                   'f': f"{WORK_DIR}/{it['file']}", 'v': f"{WORK_DIR}/{it['svg']}"} for it in main_items],
        'idxS': idxS, 'idxT': idxT}]}]}
    open(f'{SITE}/网站/db.js', 'w').write('window.DB=' + json.dumps(db, ensure_ascii=False) + ';\n')
    ver = time.strftime('%Y%m%d%H%M')
    page = open(f'{align.ROOT}/v2/site_tpl.html').read()
    open(f'{SITE}/index.html', 'w').write(page.replace('/*DBSRC*/', f'网站/db.js?v={ver}').replace('/*BASE*/', ''))
    open(f'{SITE}/网站/index.html', 'w').write(page.replace('/*DBSRC*/', f'db.js?v={ver}').replace('/*BASE*/', '../'))
    pages = sorted({it['page'] for it in main_items})
    print(f'字图 {len(main_items)}（另有夹注 {len(items) - len(main_items)}）/ {len(idxT)} 字，页 {pages[0]}–{pages[-1]} 共 {len(pages)} 页 -> {SITE}')

if __name__ == '__main__':
    main()
