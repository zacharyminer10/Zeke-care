"""Self-test for tools/checksecrets.py: every kind of secret is caught, allowed things are not.
Fake values are assembled at run time so this file itself never contains anything that looks like a key."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import checksecrets as C

j = ''.join
CATCH = {
    'Claude key': j(['sk-', 'ant-', 'api03-', 'A1b2C3d4E5f6G7h8I9j0']),
    'Claude session cookie': j(['session', 'Key=', 'sk-', 'ant-', 'sid01-', 'abcdefghijklmnop']),
    'OpenAI key': j(['sk-', 'proj-', 'A1b2C3d4E5f6G7h8I9j0K1l2']),
    'GitHub token': j(['gh', 'p_', 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4']),
    'GitHub fine-grained token': j(['github', '_pat_', '11ABCDEFG0123456789_abcdef']),
    'Google key': j(['AI', 'za', 'SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6']),
    'AWS key': j(['AK', 'IA', 'ABCDEFGHIJKLMNOP']),
    'Slack token': j(['xo', 'xb-', '1234567890-abcdefghij']),
    'Stripe key': j(['sk', '_live_', 'A1b2C3d4E5f6G7h8']),
    'private key': j(['-----BEGIN ', 'RSA PRIVATE', ' KEY-----']),
    'JWT': j(['ey', 'JhbGciOiJIUzI1NiJ9', '.', 'ey', 'JzdWIiOiIxMjM0NTY3ODkwIn0', '.', 'abcdefghijklmnopqrst']),
    'password in code': j(['pass', 'word = "', 'hunter22secret', '"']),
    'api key in code': j(['api', '_key: \'', 'abcd1234efgh5678', '\'']),
    'URL with password': j(['https://', 'zach:', 'mypassword', '@example.org/x']),
    'personal email': j(['someone', '.personal', '@', 'gmail.com']),
    'phone number': j(['(312) ', '555-', '7788']),
}
ALLOW = ['ezaide.app' + '@gmail.com', 'noreply' + '@anthropic.com', 'zacharyminer10' + '@users.noreply.github.com',
         'Call 911 first in any emergency.', 'Dr. Lee 555-0100', 'var pin=\'1111\'', 'class="pinin" maxlength="4"',
         'https://ezaide.app/privacy.html', 'S.adminPin=\'1234\'']
bad = []
for name, text in CATCH.items():
    if not C.scan_text('x', text): bad.append('MISSED ' + name)
for text in ALLOW:
    if C.scan_text('x', text): bad.append('FALSE ALARM ' + text)
for f in ['.env', 'config/.env.local', 'server.pem', 'id_rsa', 'credentials.json', '.claude/settings.local.json']:
    if not C.scan_file(f, b'x'): bad.append('MISSED credential file ' + f)
print('\n'.join(bad) or f'Secrets checker self-test: all {len(CATCH)} kinds caught, {len(ALLOW)} allowed things left alone.')
sys.exit(1 if bad else 0)
