# 汇总各帖单字成品图 -> 字库 + 网站数据（格式与 v1 的 manifest.json / index.json / 网站/db.js 一致）
# 输出到暂存目录 v2/site/，可直接作为静态站点部署
#   site/index.html                     页面（引用 网站/db.js）
#   site/网站/{index.html, db.js}        同一页面的另一份拷贝（引用 db.js）
#   site/<作品>/manifest.json, index.json, index_simplified.json
#   site/<作品>/glyphs/pNN_IIII.{png,svg}  透明底 PNG + 矢量 SVG
# 收录哪些帖：v2/books/*/book.json（每帖的元数据、不入库清单 skip/drop、检索别名 alias）
# 用法: python build_site.py [帖 ...]   默认全部
import json, os, glob, shutil, sys, time, subprocess
from opencc import OpenCC
import align

SITE = f'{align.ROOT}/v2/site'
ORDER = ['baomu']                      # 网站下拉里的顺序，未列出的按目录名排在后面

def glyph_dir(book):
    """各帖的成品图目录（align 按环境变量 ZIKU_BOOK 解析，这里换个子进程取）"""
    out = subprocess.check_output([sys.executable, '-c', 'import align; print(align.GL)'],
                                  env=dict(os.environ, ZIKU_BOOK=book), cwd=os.path.dirname(os.path.abspath(__file__)))
    return out.decode().strip()

def build(book, t2s):
    conf = json.load(open(f'{align.ROOT}/v2/books/{book}/book.json'))
    gl, wdir = glyph_dir(book), conf['dir']
    skip, drop = set(conf.get('skip', [])), {tuple(d) for d in conf.get('drop', [])}
    alias = conf.get('alias', {})       # 帖上的罕用异体 -> 检索用的通行字（只加简体索引，不改字头）
    lib = f'{SITE}/{wdir}'
    os.makedirs(f'{lib}/glyphs')
    items = []
    for mf in sorted(glob.glob(f'{gl}/p??/meta.json')):
        pid = os.path.basename(os.path.dirname(mf))
        for it in json.load(open(mf))['items']:
            if it['char'] in skip or (pid, it['idx']) in drop:
                continue
            gid = f"{pid}_{it['idx']:04d}"
            for ext in ('png', 'svg'):
                shutil.copy(f"{gl}/{pid}/{it['idx']:03d}.{ext}", f'{lib}/glyphs/{gid}.{ext}')
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
        a = alias.get(it['char'])
        for k in {t2s(it['char'])} | ({a, t2s(a)} if a else set()):
            idxS.setdefault(k, []).append(e)
    manifest = {'author': conf['author'], 'author_en': conf.get('author_en', ''), 'work': conf['title'],
                'dynasty': conf['dynasty'], 'source': conf.get('source', ''),
                'pipeline': 'v2（文字驱动对齐 + 墨块归属 + 透明底/矢量）',
                'built': time.strftime('%Y-%m-%d %H:%M'), 'items': items}
    json.dump(manifest, open(f'{lib}/manifest.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(idxT, open(f'{lib}/index.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(idxS, open(f'{lib}/index_simplified.json', 'w'), ensure_ascii=False, indent=1)
    pages = sorted({it['page'] for it in main_items})
    print(f'{book}: 字图 {len(main_items)}（另有夹注 {len(items) - len(main_items)}）/ {len(idxT)} 字，'
          f'页 {pages[0]}–{pages[-1]} 共 {len(pages)} 页')
    work = {'key': conf['key'], 'title': conf['title'], 'source': conf.get('source', ''), 'count': len(main_items),
            'items': [{'id': it['id'], 'ch': it['char'], 'page': it['page'],
                       'f': f"{wdir}/{it['file']}", 'v': f"{wdir}/{it['svg']}"} for it in main_items],
            'idxS': idxS, 'idxT': idxT}
    return conf, work

def main():
    t2s = OpenCC('t2s').convert
    books = sys.argv[1:] or sorted((os.path.basename(os.path.dirname(f))
                                    for f in glob.glob(f'{align.ROOT}/v2/books/*/book.json')),
                                   key=lambda b: (b not in ORDER, ORDER.index(b) if b in ORDER else 0, b))
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(f'{SITE}/网站')
    authors = []
    for book in books:
        conf, work = build(book, t2s)
        a = next((a for a in authors if a['name'] == conf['author']), None)
        if a is None:
            a = {'name': conf['author'], 'dynasty': conf['dynasty'], 'works': []}
            authors.append(a)
        a['works'].append(work)
    open(f'{SITE}/网站/db.js', 'w').write('window.DB=' + json.dumps({'authors': authors}, ensure_ascii=False) + ';\n')
    ver = time.strftime('%Y%m%d%H%M')
    page = open(f'{align.ROOT}/v2/site_tpl.html').read()
    open(f'{SITE}/index.html', 'w').write(page.replace('/*DBSRC*/', f'网站/db.js?v={ver}').replace('/*BASE*/', ''))
    open(f'{SITE}/网站/index.html', 'w').write(page.replace('/*DBSRC*/', f'db.js?v={ver}').replace('/*BASE*/', '../'))
    print(f'-> {SITE}')

if __name__ == '__main__':
    main()
