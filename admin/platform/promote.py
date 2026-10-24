# platform 上架：~/ziku-admin/incoming/<任务号>/ -> 线上 ziku/
# 收货包只允许：网站/db.js + 恰好一个帖目录（manifest/index/index_simplified.json + glyphs/*.png|svg）
# 新 db.js 必须包含线上现有的全部帖（只许加、许替换同 key 的那一部，不许少）
# 上架前把线上 db.js、两份 index.html 和同名帖目录备份到 backups/<时间>-<任务号>/，再原子替换
import json, os, re, shutil, sys, time

LIVE = '/home/op/platform-docker/web/web2/ziku'
HOME = '/home/op/ziku-admin'
jid = sys.argv[1]
assert re.fullmatch(r'\d{14}-[0-9a-f]{6}', jid)
src = f'{HOME}/incoming/{jid}'

def die(msg):
    print('拒绝：' + msg, file=sys.stderr)
    sys.exit(2)

def parse_db(p):
    s = open(p, encoding='utf-8').read()
    return json.loads(s[s.index('=') + 1:s.rstrip().rindex(';')])

top = sorted(os.listdir(src))
books = [d for d in top if d != '网站']
if sorted(os.listdir(f'{src}/网站')) != ['db.js'] or len(books) != 1 or len(top) != 2:
    die(f'收货包结构不对：{top}')
book = books[0]
if not re.fullmatch(r'[㐀-鿿豈-﫿·（）()A-Za-z0-9-]{3,40}', book) or book == '网站':
    die(f'帖目录名不合规：{book}')
B = f'{src}/{book}'
if sorted(os.listdir(B)) != ['glyphs', 'index.json', 'index_simplified.json', 'manifest.json']:
    die(f'帖目录内容不对：{os.listdir(B)}')
gl = os.listdir(f'{B}/glyphs')
bad = [g for g in gl if not re.fullmatch(r'p\d{2,3}_\d{4}\.(png|svg)', g) or os.path.islink(f'{B}/glyphs/{g}')]
if bad or not gl:
    die(f'glyphs 里有不认识的文件：{bad[:5]}')
for g in gl:                                   # 文件头校验：PNG 魔数 / SVG 不许带脚本
    head = open(f'{B}/glyphs/{g}', 'rb').read(4096)
    if g.endswith('.png') and not head.startswith(b'\x89PNG'):
        die(f'{g} 不是 PNG')
    if g.endswith('.svg') and (not head.startswith(b'<svg') or re.search(rb'<script|on\w+=|href', open(f'{B}/glyphs/{g}', 'rb').read(), re.I)):
        die(f'{g} SVG 不合规')
for j in ('manifest.json', 'index.json', 'index_simplified.json'):
    json.load(open(f'{B}/{j}', encoding='utf-8'))
new, live = parse_db(f'{src}/网站/db.js'), parse_db(f'{LIVE}/网站/db.js')
keys = lambda d: {w['key'] for a in d['authors'] for w in a['works']}
if not keys(live) <= keys(new) or len(keys(new)) - len(keys(live)) > 1:
    die(f'db.js 帖目不对：线上 {len(keys(live))} 部，新 {len(keys(new))} 部，缺 {sorted(keys(live) - keys(new))}')
bdir = {w['items'][0]['f'].split('/')[0] for a in new['authors'] for w in a['works'] if w['items']}
if book not in bdir:
    die(f'db.js 里没有引用 {book}')

bk = f'{HOME}/backups/{time.strftime("%Y%m%d-%H%M%S")}-{jid}'
os.makedirs(f'{bk}/网站')
shutil.copy2(f'{LIVE}/网站/db.js', f'{bk}/网站/db.js')
shutil.copy2(f'{LIVE}/index.html', f'{bk}/index.html')
shutil.copy2(f'{LIVE}/网站/index.html', f'{bk}/网站/index.html')
if os.path.exists(f'{LIVE}/{book}'):
    shutil.copytree(f'{LIVE}/{book}', f'{bk}/{book}')
# 上架：帖目录先放到旁边再改名（同一文件系统，rename 原子），db.js 同理
tmp = f'{LIVE}/.{book}.new'
shutil.rmtree(tmp, ignore_errors=True)
shutil.copytree(B, tmp)
old = f'{LIVE}/.{book}.old'
shutil.rmtree(old, ignore_errors=True)
if os.path.exists(f'{LIVE}/{book}'):
    os.rename(f'{LIVE}/{book}', old)
os.rename(tmp, f'{LIVE}/{book}')
shutil.rmtree(old, ignore_errors=True)
shutil.copy2(f'{src}/网站/db.js', f'{LIVE}/网站/.db.js.new')
os.rename(f'{LIVE}/网站/.db.js.new', f'{LIVE}/网站/db.js')
ver = time.strftime('%Y%m%d%H%M')               # 两份页面里 db.js?v= 换新，浏览器不吃旧缓存
for p in (f'{LIVE}/index.html', f'{LIVE}/网站/index.html'):
    s = open(p, encoding='utf-8').read()
    open(p + '.new', 'w', encoding='utf-8').write(re.sub(r'db\.js\?v=\d+', f'db.js?v={ver}', s))
    os.rename(p + '.new', p)
shutil.rmtree(src)
print(json.dumps({'ok': True, 'book': book, 'glyph_files': len(gl), 'works': len(keys(new)), 'backup': bk}, ensure_ascii=False))
