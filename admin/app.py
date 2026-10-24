# 字库后台（网页端）：登录（口令 + TOTP）、上传原帖、看处理报告与预览、批准发布
# 这个进程手里没有任何通往生产服务器的凭据：上传只落到 inbox/，「发布」只写一条批准记录，真正处理和上线都在 worker 里
import hashlib, json, os, re, secrets, time
from flask import Flask, abort, make_response, redirect, render_template_string, request, send_from_directory
import common as C

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
COOKIE = '__Host-zka'                      # __Host-：必须 Secure、Path=/、不带 Domain，子域拿不到
IDLE, ABSOLUTE = 30 * 60, 8 * 3600
TRUST_PROXY = os.environ.get('ZKA_TRUST_PROXY') == '1'
NAME_RE = re.compile(r'^[㐀-鿿豈-﫿A-Za-z0-9·（）()《》 -]{1,40}$')   # 进页面的字段只许这些字符，杜绝注入
KEY_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$')

def ip():
    return (request.headers.get('X-Real-IP') if TRUST_PROXY else None) or request.remote_addr

# ---------- 安全头 ----------
@app.after_request
def headers(r):
    pv = request.path.startswith('/preview/')
    r.headers['Content-Security-Policy'] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        + ("script-src 'self' 'unsafe-inline'; " if pv else "script-src 'none'; ")
        + "frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
    r.headers['X-Frame-Options'] = 'DENY'
    r.headers['X-Content-Type-Options'] = 'nosniff'
    r.headers['Referrer-Policy'] = 'no-referrer'
    r.headers['Cache-Control'] = 'no-store'
    r.headers['X-Robots-Tag'] = 'noindex, nofollow'
    r.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return r

# ---------- 会话 ----------
def current():
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    c = C.db()
    s = c.execute('SELECT * FROM sessions WHERE sid=?', (hashlib.sha256(tok.encode()).hexdigest(),)).fetchone()
    now = time.time()
    if not s or now - s['seen'] > IDLE or now - s['created'] > ABSOLUTE:
        if s: c.execute('DELETE FROM sessions WHERE sid=?', (s['sid'],))
        return None
    u = c.execute('SELECT * FROM users WHERE name=? AND disabled=0', (s['user'],)).fetchone()
    if not u:
        return None
    c.execute('UPDATE sessions SET seen=? WHERE sid=?', (now, s['sid']))
    return {'user': s['user'], 'csrf': s['csrf'], 'sid': s['sid']}

def need_login():
    s = current()
    if not s:
        abort(redirect('/login'))
    if request.method == 'POST':                # CSRF：同源 + 表单令牌，两样都要
        if request.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
            abort(403)
        if not secrets.compare_digest(request.form.get('csrf', ''), s['csrf']):
            abort(403)
    return s

def ip_throttled(action, limit, window):
    c = C.db()
    n = c.execute('SELECT COUNT(*) FROM audit WHERE ip=? AND action=? AND t>?', (ip(), action, time.time() - window)).fetchone()[0]
    return n >= limit

def check_totp(user, code):
    """校验动态码并记下用掉的时间步（同一个码不能用第二次）"""
    c = C.db()
    u = c.execute('SELECT * FROM users WHERE name=?', (user,)).fetchone()
    st = C.totp_check(u['totp'], code, u['last_step'])
    if st:
        c.execute('UPDATE users SET last_step=? WHERE name=?', (st, user))
    return st is not None

# ---------- 页面 ----------
BASE = '''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>字库后台</title><style>
body{font:15px/1.6 -apple-system,"PingFang SC",sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#222;background:#faf8f3}
h1{font-size:20px} input,select,textarea,button{font:inherit;padding:6px 8px;margin:4px 0;box-sizing:border-box}
input[type=text],input[type=password],textarea,select{width:100%} button{cursor:pointer}
table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left;font-size:14px}
.err{color:#b00} .muted{color:#888;font-size:13px} .bar{display:flex;justify-content:space-between;align-items:center}
form.inline{display:inline} .card{background:#fff;border:1px solid #e3ddd0;border-radius:6px;padding:12px 16px;margin:12px 0}
</style></head><body>{% block body %}{% endblock %}</body></html>'''

def page(body, **kw):
    return render_template_string(BASE.replace('{% block body %}{% endblock %}', body), **kw)

@app.get('/login')
def login_form():
    return page('''<h1>字库后台登录</h1>{% if err %}<p class="err">{{err}}</p>{% endif %}
<form method="post" action="/login" autocomplete="off" class="card">
<label>用户名<input type="text" name="u" required autofocus></label>
<label>口令<input type="password" name="p" required></label>
<label>动态码（验证器 App 里的 6 位数）<input type="text" name="t" inputmode="numeric" pattern="[0-9]{6}" required></label>
<button>登录</button></form>''', err=request.args.get('e'))

@app.post('/login')
def login():
    if request.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
        abort(403)
    u, p, t = request.form.get('u', '')[:64], request.form.get('p', '')[:256], request.form.get('t', '')[:6]
    fail = redirect('/login?e=登录失败')                     # 统一提示，不区分哪一项错
    if ip_throttled('login-fail', 10, 600):                 # 同一 IP 10 分钟最多失败 10 次
        C.audit(u, ip(), 'login-throttled'); time.sleep(1); return fail
    c = C.db()
    row = c.execute('SELECT * FROM users WHERE name=?', (u,)).fetchone()
    ok = C.pw_check(p, row['pw'] if row else C.DUMMY)
    now = time.time()
    if not row or row['disabled'] or row['lock_until'] > now:
        C.audit(u, ip(), 'login-fail', 'locked/unknown'); return fail
    if not ok or not check_totp(u, t):
        fails = row['fails'] + 1
        if fails >= 5:                                       # 连错 5 次锁 15 分钟，每再锁一次时长翻倍
            c.execute('UPDATE users SET fails=0, lock_level=lock_level+1, lock_until=? WHERE name=?',
                      (now + 900 * 2 ** row['lock_level'], u))
        else:
            c.execute('UPDATE users SET fails=? WHERE name=?', (fails, u))
        C.audit(u, ip(), 'login-fail'); return fail
    c.execute('UPDATE users SET fails=0, lock_level=0 WHERE name=?', (u,))
    tok = secrets.token_urlsafe(32)                          # 256 位；库里只存哈希，库泄露也拿不到可用的会话
    c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)', (hashlib.sha256(tok.encode()).hexdigest(), u,
              secrets.token_urlsafe(24), now, now, ip(), request.headers.get('User-Agent', '')[:200]))
    C.audit(u, ip(), 'login-ok', request.headers.get('User-Agent', '')[:200])
    r = redirect('/')
    r.set_cookie(COOKIE, tok, secure=True, httponly=True, samesite='Strict', path='/', max_age=ABSOLUTE)
    return r

@app.post('/logout')
def logout():
    s = need_login()
    c = C.db()
    if request.form.get('all'):
        c.execute('DELETE FROM sessions WHERE user=?', (s['user'],))
    else:
        c.execute('DELETE FROM sessions WHERE sid=?', (s['sid'],))
    C.audit(s['user'], ip(), 'logout-all' if request.form.get('all') else 'logout')
    r = redirect('/login'); r.delete_cookie(COOKIE, path='/', secure=True, samesite='Strict'); return r

@app.get('/')
def home():
    s = need_login()
    jobs = C.db().execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 50').fetchall()
    return page('''<div class="bar"><h1>字库后台</h1><span>{{s.user}}
<form class="inline" method="post" action="/logout"><input type="hidden" name="csrf" value="{{s.csrf}}"><button>退出</button></form>
<form class="inline" method="post" action="/logout"><input type="hidden" name="csrf" value="{{s.csrf}}"><input type="hidden" name="all" value="1"><button>退出全部设备</button></form></span></div>
<div class="card"><h3>上传原帖</h3>
<form method="post" action="/upload" enctype="multipart/form-data">
<input type="hidden" name="csrf" value="{{s.csrf}}">
<label>帖的英文代号（小写字母、数字、连字符，如 liugongquan-xuanmita）<input type="text" name="key" required pattern="[a-z0-9][a-z0-9-]{1,38}[a-z0-9]"></label>
<label>书法家<input type="text" name="author" required></label><label>朝代<input type="text" name="dynasty" required></label>
<label>帖名<input type="text" name="title" required></label>
<label>书体<select name="script"><option>楷书</option><option>行书</option></select></label>
<label>全文释文（与帖上一致，标点会自动去掉；按页序从第一页第一字开始）<textarea name="text" rows="6" required></textarea></label>
<label>页面图压缩包（zip / rar，按文件名排序即页序，≤500MB）<input type="file" name="file" accept=".zip,.rar" required></label>
<button>上传</button></form></div>
<h3>任务</h3><table><tr><th>时间</th><th>帖</th><th>状态</th><th></th></tr>
{% for j in jobs %}<tr><td>{{ fmt(j.created) }}</td><td>{{j.author}}《{{j.title}}》</td><td>{{j.status}}</td><td><a href="/job/{{j.id}}">查看</a></td></tr>{% endfor %}
</table>''', s=s, jobs=jobs, fmt=lambda t: time.strftime('%m-%d %H:%M', time.localtime(t)))

@app.post('/upload')
def upload():
    s = need_login()
    f = request.form
    key, author, dyn, title, script, text = (f.get(k, '').strip() for k in ('key', 'author', 'dynasty', 'title', 'script', 'text'))
    han = sum('㐀' <= ch <= '鿿' or '豈' <= ch <= '﫿' for ch in text)
    errs = []
    if not KEY_RE.match(key): errs.append('代号格式不对')
    if not all(NAME_RE.match(x) for x in (author, dyn, title)): errs.append('书法家/朝代/帖名含不允许的字符')
    if script not in ('楷书', '行书'): errs.append('书体只能是楷书或行书')
    if han < 20 or len(text) > 200000: errs.append('释文太短或太长')
    up = request.files.get('file')
    head = up.stream.read(8) if up else b''
    kind = 'zip' if head.startswith(b'PK\x03\x04') else 'rar' if head.startswith(b'Rar!\x1a\x07') else None
    if not kind: errs.append('只收 zip / rar（按文件头判断，不看扩展名）')
    if errs:
        C.audit(s['user'], ip(), 'upload-reject', '; '.join(errs))
        return page('<p class="err">{{e}}</p><p><a href="/">返回</a></p>', e='；'.join(errs)), 400
    jid = time.strftime('%Y%m%d%H%M%S') + '-' + secrets.token_hex(3)
    d = f'{C.DATA}/inbox/{jid}'
    os.makedirs(d, mode=0o700)
    with open(f'{d}/upload.{kind}', 'wb') as o:               # 原文件名一律丢掉
        o.write(head)
        while chunk := up.stream.read(1 << 20):
            o.write(chunk)
    json.dump({'key': key, 'author': author, 'dynasty': dyn, 'title': title, 'script': script, 'text': text,
               'kind': kind, 'user': s['user']}, open(f'{d}/job.json', 'w'), ensure_ascii=False)
    open(f'{d}/READY', 'w').close()                          # worker 只认带 READY 的目录，避免读到写了一半的上传
    C.db().execute('INSERT INTO jobs(id,key,title,author,user,created,status) VALUES(?,?,?,?,?,?,?)',
                   (jid, key, title, author, s['user'], time.time(), '排队中'))
    C.audit(s['user'], ip(), 'upload', f'{jid} {key} {os.path.getsize(f"{d}/upload.{kind}")}B')
    return redirect(f'/job/{jid}')

def job_or_404(jid):
    if not re.fullmatch(r'\d{14}-[0-9a-f]{6}', jid):
        abort(404)
    j = C.db().execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
    if not j: abort(404)
    return j

@app.get('/job/<jid>')
def job(jid):
    s = need_login()
    j = job_or_404(jid)
    rep = json.loads(j['report']) if j['report'] else None
    return page('''<p><a href="/">← 返回</a></p><h1>{{j.author}}《{{j.title}}》</h1>
<p>状态：<b>{{j.status}}</b>{% if j.approved_by %}（{{j.approved_by}} 批准）{% endif %}</p>
{% if rep %}<div class="card"><table>
<tr><td>页数</td><td>{{rep.pages}}</td></tr><tr><td>释文字数</td><td>{{rep.text_chars}}</td></tr>
<tr><td>切出字图</td><td>{{rep.glyphs}}（自动剔除 {{rep.auto_drop}}，缺字 {{rep.missing}}）</td></tr>
<tr><td>失败页</td><td>{{rep.failed_pages|join(' ') or '无'}}</td></tr>
<tr><td>判定</td><td>{{ '可预览后发布' if rep.status=='review' else '需人工处理（转 agent）' }}</td></tr>
</table></div>
<p><a href="/preview/{{j.id}}/index.html" target="_blank" rel="noopener">打开预览</a> <span class="muted">（只在后台可见）</span></p>
{% if rep.status=='review' and j.status=='待审核' %}
<form method="post" action="/job/{{j.id}}/publish" class="card"><input type="hidden" name="csrf" value="{{s.csrf}}">
<label>发布需要再输一次动态码<input type="text" name="t" inputmode="numeric" pattern="[0-9]{6}" required></label>
<button>批准发布</button></form>{% endif %}{% endif %}''', s=s, j=j, rep=rep)

@app.post('/job/<jid>/publish')
def publish(jid):
    s = need_login()
    j = job_or_404(jid)
    if j['status'] != '待审核':
        abort(409)
    if not check_totp(s['user'], request.form.get('t', '')):
        C.audit(s['user'], ip(), 'publish-totp-fail', jid)
        return page('<p class="err">动态码不对</p><p><a href="/job/{{jid}}">返回</a></p>', jid=jid), 403
    C.db().execute("UPDATE jobs SET status='已批准', approved_by=?, approved=? WHERE id=?", (s['user'], time.time(), jid))
    open(f'{C.DATA}/jobs/{jid}/APPROVED', 'w').write(s['user'])
    C.audit(s['user'], ip(), 'publish-approve', jid)
    return redirect(f'/job/{jid}')

@app.get('/preview/<jid>/<path:p>')
def preview(jid, p):
    need_login()
    job_or_404(jid)
    return send_from_directory(f'{C.DATA}/preview/{jid}', p)   # send_from_directory 拒绝 .. 和绝对路径

@app.errorhandler(413)
def too_big(e):
    return page('<p class="err">文件超过 500MB</p>'), 413

C.init()
