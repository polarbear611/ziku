# 账号只能在这里管（网页上没有注册、找回）。在 NAS 上：
#   docker compose exec web python manage.py add <用户名>        建号：读口令（≥14 位，输两次），打印 TOTP 绑定串和终端二维码
#   docker compose exec web python manage.py reset-pw <用户名>   改口令（会话全部作废）
#   docker compose exec web python manage.py reset-totp <用户名> 重新绑定动态码
#   docker compose exec web python manage.py disable|enable|unlock <用户名>
#   docker compose exec web python manage.py kick <用户名>       踢掉该用户全部会话
#   docker compose exec web python manage.py audit [条数]        看审计日志
import getpass, sys, time
import common as C

def ask_pw():
    p1 = getpass.getpass('口令（≥14 位）: ')
    if len(p1) < 14:
        sys.exit('口令太短')
    if getpass.getpass('再输一次: ') != p1:
        sys.exit('两次不一致')
    return p1

def show_totp(user, secret):
    uri = C.totp_uri(user, secret)
    print('\n用手机验证器 App（Google Authenticator / Microsoft Authenticator 等）扫码或手动输入：')
    print('  密钥：', secret)
    try:
        import qrcode
        q = qrcode.QRCode(border=1); q.add_data(uri); q.print_ascii(invert=True)
    except ImportError:
        print('  ', uri)
    print('此密钥只显示这一次，网页上取不到。\n')

def main():
    C.init()
    c = C.db()
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == 'add':
        u = args[0]
        if c.execute('SELECT 1 FROM users WHERE name=?', (u,)).fetchone():
            sys.exit('已存在')
        s = C.totp_new()
        c.execute('INSERT INTO users(name, pw, totp) VALUES(?,?,?)', (u, C.pw_hash(ask_pw()), s))
        show_totp(u, s); C.audit(u, 'cli', 'user-add')
    elif cmd == 'reset-pw':
        c.execute('UPDATE users SET pw=? WHERE name=?', (C.pw_hash(ask_pw()), args[0]))
        c.execute('DELETE FROM sessions WHERE user=?', (args[0],)); C.audit(args[0], 'cli', 'pw-reset')
    elif cmd == 'reset-totp':
        s = C.totp_new()
        c.execute('UPDATE users SET totp=?, last_step=0 WHERE name=?', (s, args[0]))
        c.execute('DELETE FROM sessions WHERE user=?', (args[0],)); show_totp(args[0], s); C.audit(args[0], 'cli', 'totp-reset')
    elif cmd in ('disable', 'enable'):
        c.execute('UPDATE users SET disabled=? WHERE name=?', (cmd == 'disable', args[0]))
        c.execute('DELETE FROM sessions WHERE user=?', (args[0],)); C.audit(args[0], 'cli', cmd)
    elif cmd == 'unlock':
        c.execute('UPDATE users SET fails=0, lock_until=0, lock_level=0 WHERE name=?', (args[0],))
    elif cmd == 'kick':
        c.execute('DELETE FROM sessions WHERE user=?', (args[0],))
    elif cmd == 'audit':
        for r in c.execute('SELECT * FROM audit ORDER BY t DESC LIMIT ?', (int(args[0]) if args else 50,)):
            print(time.strftime('%m-%d %H:%M:%S', time.localtime(r['t'])), r['user'], r['ip'], r['action'], r['detail'])
    else:
        sys.exit(__doc__)

if __name__ == '__main__':
    main()
