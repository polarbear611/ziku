# 字库后台（处理端）：每 2 分钟扫 inbox/，一次处理一部帖：安全解包 -> auto_ingest -> 预览站；
# 管理员批准后：并入发布目录 release/（新帖字图 + 合并后的 db.js）；配了 ZKA_DEPLOY 时再推到线上
import glob, json, os, shutil, stat, subprocess, sys, time, traceback, urllib.request, zipfile
from PIL import Image
import common as C

V2 = os.environ.get('ZIKU_V2', '/app/v2')
PY = f'{V2}/venv/bin/python' if os.path.exists(f'{V2}/venv/bin/python') else sys.executable
LIVE_DB = os.environ.get('ZKA_LIVE_DB', 'https://ziku.xlingdata.com/%E7%BD%91%E7%AB%99/db.js')
MAX_FILES, MAX_TOTAL, MAX_PIXELS = 500, 2 * 1024 ** 3, 60_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
IMG_EXT = ('.webp', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')

def setstatus(jid, st, report=None):
    c = C.db()
    if report is None:
        c.execute('UPDATE jobs SET status=? WHERE id=?', (st, jid))
    else:
        c.execute('UPDATE jobs SET status=?, report=? WHERE id=?', (st, json.dumps(report, ensure_ascii=False), jid))
    C.audit('worker', 'local', 'status', f'{jid} {st}')

def safe_name(n):
    return n and not n.startswith('/') and '..' not in n.split('/') and '\\' not in n and '\x00' not in n

def unpack(arc, kind, out):
    """只解普通文件；拒绝绝对路径、..、链接、设备；数量和解压后总量都设上限（防压缩炸弹）"""
    tmp = f'{out}.raw'
    shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(out, ignore_errors=True)   # 重跑时清掉上次的残留
    os.makedirs(tmp)
    if kind == 'zip':
        with zipfile.ZipFile(arc) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL:
                raise ValueError('文件太多或解压后太大')
            for i in infos:
                if not safe_name(i.filename) or stat.S_ISLNK(i.external_attr >> 16):
                    raise ValueError(f'不安全的条目：{i.filename!r}')
            z.extractall(tmp, infos)
    else:
        ls = subprocess.run(['bsdtar', '-tvf', arc], capture_output=True, text=True, check=True).stdout.splitlines()
        if len(ls) > MAX_FILES * 2:
            raise ValueError('条目太多')
        total = 0
        for l in ls:
            if l[0] not in '-d':                              # 只许普通文件和目录
                raise ValueError(f'不安全的条目：{l!r}')
            parts = l.split(None, 8)
            total += int(parts[4])
            if not safe_name(parts[8].rstrip('/')):
                raise ValueError(f'不安全的条目：{parts[8]!r}')
        if total > MAX_TOTAL:
            raise ValueError('解压后太大')
        subprocess.run(['bsdtar', '-xf', arc, '-C', tmp, '--no-same-owner', '--no-same-permissions'], check=True)
    # 逐张用 Pillow 打开、重编码成 PNG，按原路径排序编号；非图片一律丢掉
    files = sorted(p for p in glob.glob(f'{tmp}/**/*', recursive=True)
                   if os.path.isfile(p) and not os.path.islink(p) and p.lower().endswith(IMG_EXT)
                   and not os.path.basename(p).startswith(('._', '.')))
    if not files:
        raise ValueError('压缩包里没有图片')
    os.makedirs(out)
    for k, p in enumerate(files, 1):
        with Image.open(p) as im:
            im.load()
            im.convert('RGB').save(f'{out}/{k:03d}.png')
    shutil.rmtree(tmp)
    return len(files)

def process(jid):
    src = f'{C.DATA}/inbox/{jid}'
    d = f'{C.DATA}/jobs/{jid}'
    os.rename(src, d)                                         # 认领：挪出 inbox，web 端再看不到也改不了
    J = json.load(open(f'{d}/job.json'))
    setstatus(jid, '解包中')
    n = unpack(f'{d}/upload.{J["kind"]}', J['kind'], f'{d}/src')
    setstatus(jid, f'处理中（{n} 页）')
    env = dict(os.environ, ZIKU_BOOKS_DIR=f'{C.DATA}/staging')
    r = subprocess.run([PY, f'{V2}/auto_ingest.py', d], cwd=V2, env=env, capture_output=True, text=True)
    open(f'{d}/ingest.log', 'w').write(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    rep = json.load(open(f'{C.DATA}/staging/{J["key"]}/report.json'))
    # 预览站：只含这一部帖
    pv = f'{C.DATA}/preview/{jid}'
    shutil.rmtree(pv, ignore_errors=True)
    r = subprocess.run([PY, f'{V2}/build_site.py', J['key']], cwd=V2, capture_output=True, text=True,
                       env=dict(env, ZIKU_SITE=pv, ZIKU_BOOK=J['key']))
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    setstatus(jid, '待审核' if rep['status'] == 'review' else '需人工', rep)

def merge_db(live_js, new_js):
    """线上 db.js + 新帖（同 key 则替换） -> 新 db.js；只动这一部帖，别的帖原样保留"""
    strip = lambda s: json.loads(s[s.index('=') + 1:s.rstrip().rindex(';')])
    live, new = strip(live_js), strip(new_js)
    for na in new['authors']:
        for w in na['works']:
            for a in live['authors']:
                a['works'] = [x for x in a['works'] if x['key'] != w['key']]
            a = next((a for a in live['authors'] if a['name'] == na['name']), None)
            if a is None:
                live['authors'].append(a := {'name': na['name'], 'dynasty': na['dynasty'], 'works': []})
            a['works'].append(w)
    live['authors'] = [a for a in live['authors'] if a['works']]
    return 'window.DB=' + json.dumps(live, ensure_ascii=False) + ';\n'

def release(jid):
    d = f'{C.DATA}/jobs/{jid}'
    J = json.load(open(f'{d}/job.json'))
    pv = f'{C.DATA}/preview/{jid}'
    conf = json.load(open(f'{C.DATA}/staging/{J["key"]}/book.json'))
    rel = f'{C.DATA}/release/{jid}'
    shutil.rmtree(rel, ignore_errors=True)
    os.makedirs(f'{rel}/网站')
    shutil.copytree(f'{pv}/{conf["dir"]}', f'{rel}/{conf["dir"]}')
    live = urllib.request.urlopen(LIVE_DB, timeout=60).read().decode()
    open(f'{rel}/网站/db.js', 'w').write(merge_db(live, open(f'{pv}/网站/db.js').read()))
    deploy = os.environ.get('ZKA_DEPLOY')                     # 第 2 步才配：推 platform 的脚本（密钥只在本容器）
    if deploy:
        r = subprocess.run([deploy, rel, conf['dir']], capture_output=True, text=True)
        open(f'{d}/deploy.log', 'w').write(r.stdout + r.stderr)
        if r.returncode:
            raise RuntimeError('上线失败：' + r.stderr[-500:])
        setstatus(jid, '已上线')
    else:
        setstatus(jid, '已生成发布包（未配置上线）')
    os.remove(f'{d}/APPROVED')

def tick():
    for p in sorted(glob.glob(f'{C.DATA}/inbox/*/READY'))[:1]:     # 一次只处理一部
        jid = p.split('/')[-2]
        try:
            process(jid)
        except Exception as e:
            traceback.print_exc()
            setstatus(jid, f'失败：{str(e)[:200]}')
    for p in sorted(glob.glob(f'{C.DATA}/jobs/*/APPROVED')):
        jid = p.split('/')[-2]
        try:
            release(jid)
        except Exception as e:
            traceback.print_exc()
            setstatus(jid, f'发布失败：{str(e)[:200]}')

if __name__ == '__main__':
    C.init()
    every = int(os.environ.get('ZKA_EVERY', 120))
    while True:
        tick()
        if '--once' in sys.argv:
            break
        time.sleep(every)
