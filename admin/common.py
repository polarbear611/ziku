# 字库后台公共部分：路径、数据库、口令哈希、TOTP、审计
# 数据全在 DATA（容器里挂 NAS 卷）：db.sqlite（账号/会话/任务/审计，0600）、inbox/ jobs/ staging/ preview/ release/
import base64, hashlib, hmac, json, os, secrets, sqlite3, struct, time

DATA = os.environ.get('ZKA_DATA', '/data')
DB = f'{DATA}/db.sqlite'

def db():
    c = sqlite3.connect(DB, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    return c

def init():
    for d in ('inbox', 'jobs', 'staging', 'preview', 'release'):
        os.makedirs(f'{DATA}/{d}', exist_ok=True)
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, pw TEXT, totp TEXT, disabled INT DEFAULT 0,
        fails INT DEFAULT 0, lock_until REAL DEFAULT 0, lock_level INT DEFAULT 0, last_step INT DEFAULT 0);
    CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY, user TEXT, csrf TEXT, created REAL, seen REAL, ip TEXT, ua TEXT);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, key TEXT, title TEXT, author TEXT, user TEXT, created REAL,
        status TEXT, report TEXT, approved_by TEXT, approved REAL);
    CREATE TABLE IF NOT EXISTS audit(t REAL, user TEXT, ip TEXT, action TEXT, detail TEXT);
    ''')
    os.chmod(DB, 0o600)

def audit(user, ip, action, detail=''):
    db().execute('INSERT INTO audit VALUES(?,?,?,?,?)', (time.time(), user, ip, action, detail[:500]))

# ---------- 口令：scrypt（N=2^15, r=8, p=1，约 32MB 内存/次），带盐 ----------
def pw_hash(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
    return 'scrypt$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(h).decode()

def pw_check(pw, stored):
    try:
        _, s, h = stored.split('$')
        x = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(x, base64.b64decode(h))
    except Exception:
        return False

DUMMY = pw_hash(secrets.token_hex(16))      # 用户不存在时也算一次哈希，响应时间不暴露账号是否存在

# ---------- TOTP（RFC 6238，SHA1/30s/6 位，前后各容 1 步；同一步不许重用） ----------
def totp_new():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')

def _hotp(key, step):
    d = hmac.new(key, struct.pack('>Q', step), 'sha1').digest()
    o = d[-1] & 15
    return '%06d' % ((struct.unpack('>I', d[o:o + 4])[0] & 0x7fffffff) % 1000000)

def totp_check(secret, code, last_step):
    """-> 命中的时间步（> last_step 才算），否则 None"""
    if not (code and code.isdigit() and len(code) == 6):
        return None
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    now = int(time.time() // 30)
    for st in (now - 1, now, now + 1):
        if st > last_step and hmac.compare_digest(_hotp(key, st), code):
            return st
    return None

def totp_uri(user, secret):
    return f'otpauth://totp/ziku-admin:{user}?secret={secret}&issuer=ziku-admin&algorithm=SHA1&digits=6&period=30'

def read_json(p, default=None):
    try:
        return json.load(open(p))
    except Exception:
        return default
