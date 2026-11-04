"""Authenticated bounded Jupyter control; deletes only its own kernel.

Adapted from this project's independently exercised Jupyter client.
Credentials remain in memory and never enter scripts, reports or URLs.
"""
from datetime import datetime,timezone
from html.parser import HTMLParser
import http.cookiejar,json,re,socket,time,uuid,websocket
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode,urljoin,urlsplit,urlunsplit
from urllib.request import HTTPCookieProcessor,Request,build_opener,ProxyHandler
PREFIX='__REVIEW_RESULT__='
class JupyterError(RuntimeError):
    """An error safe to show without exposing authentication headers."""


def network_error_detail(exc):
    """Preserve actionable OS codes without echoing URLs, cookies or secrets."""
    reason=exc.reason if isinstance(exc,URLError) else exc
    code=getattr(reason,'winerror',None) or getattr(reason,'errno',None)
    code=code if type(code) is int else None
    name=type(reason).__name__
    suffix=f' (OS code {code})' if code is not None else ''
    if code in (10013,13,1):
        hint='操作系统禁止局域网连接，请检查 VPN 的局域网访问设置和防火墙策略。'
    elif code in (10051,10065,101,113):
        hint='没有到开发板的可用路由，请检查电脑与开发板的 IP 网段和网线。'
    elif code in (10061,111):
        hint='板端拒绝连接，请确认 Jupyter 服务已启动且端口正确。'
    elif isinstance(reason,(TimeoutError,socket.timeout)) or code in (10060,110):
        hint='连接开发板超时，请检查网线、IP 网段和板端服务。'
    else:
        hint='无法连接板端 Jupyter，请检查连接地址及本机网络策略。'
    return f'{name}{suffix}；{hint}'

class XsrfParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'input':
            values = dict(attrs)
            if values.get('name') == '_xsrf':
                self.token = values.get('value')

def normalize_base_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise JupyterError('--url must be an http:// or https:// Jupyter URL')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise JupyterError('--url must not contain credentials, query, or fragment')
    path = parsed.path.rstrip('/')
    if path.endswith('/lab') or path.endswith('/tree') or path.endswith('/login'):
        path = path.rsplit('/', 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, path + '/', '', ''))

class JupyterClient:

    def __init__(self, base_url, http_timeout):
        self.base_url = normalize_base_url(base_url)
        self.origin = urlunsplit(urlsplit(self.base_url)._replace(path='', query='', fragment=''))
        self.http_timeout = http_timeout
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(ProxyHandler({}),HTTPCookieProcessor(self.cookies))

    def url(self, relative_path):
        return urljoin(self.base_url, relative_path.lstrip('/'))

    def xsrf_cookie(self):
        for cookie in self.cookies:
            if cookie.name == '_xsrf':
                return cookie.value
        return None

    def request(self, method, relative_path, *, data=None, content_type=None, max_bytes=1024 * 1024, expected=(200,)):
        headers = {'Accept': 'application/json', 'Referer': self.base_url, 'User-Agent': 'pynq-remote-jupyter-test/1'}
        if content_type:
            headers['Content-Type'] = content_type
        if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            headers['Origin'] = self.origin
            token = self.xsrf_cookie()
            if token:
                headers['X-XSRFToken'] = token
        req = Request(self.url(relative_path), data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.http_timeout) as response:
                if response.status not in expected:
                    raise JupyterError(f'HTTP {response.status} for {method} {relative_path}')
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise JupyterError(f'response too large for {method} {relative_path}')
                return body
        except HTTPError as exc:
            raise JupyterError(f'HTTP {exc.code} for {method} {relative_path}') from None
        except (URLError, OSError) as exc:
            raise JupyterError(f'network error for {method} {relative_path}: {network_error_detail(exc)}') from None

    def json_request(self, method, relative_path, *, data=None, max_bytes=1024 * 1024, expected=(200,)):
        body = self.request(method, relative_path, data=None if data is None else json.dumps(data).encode('utf-8'), content_type='application/json' if data is not None else None, max_bytes=max_bytes, expected=expected)
        try:
            value = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise JupyterError(f'expected Jupyter JSON from {method} {relative_path}') from None
        if not isinstance(value, dict):
            raise JupyterError(f'unexpected Jupyter JSON from {method} {relative_path}')
        return value

    def login(self, password):
        next_path = urlsplit(self.base_url).path
        login_path = 'login?' + urlencode({'next': next_path})
        page = self.request('GET', login_path, max_bytes=1024 * 1024)
        parser = XsrfParser()
        parser.feed(page.decode('utf-8', errors='replace'))
        token = parser.token or self.xsrf_cookie()
        if not token:
            raise JupyterError('Jupyter login did not supply an _xsrf token')
        form = urlencode({'password': password, '_xsrf': token, 'next': next_path}).encode('utf-8')
        self.request('POST', login_path, data=form, content_type='application/x-www-form-urlencoded', max_bytes=1024 * 1024)
        specs = self.json_request('GET', 'api/kernelspecs')
        if not isinstance(specs.get('kernelspecs'), dict):
            raise JupyterError('Jupyter login did not grant API access')
        return specs

    def choose_kernel(self, specs, requested):
        names = specs['kernelspecs']
        name = requested or ('python3' if 'python3' in names else specs.get('default'))
        if not isinstance(name, str) or name not in names:
            raise JupyterError('no usable Python kernel spec; choose one with --kernel-name')
        return name

    def create_kernel(self, name):
        model = self.json_request('POST', 'api/kernels', data={'name': name}, expected=(200, 201))
        kernel_id = model.get('id')
        try:
            uuid.UUID(kernel_id)
        except (TypeError, ValueError, AttributeError):
            raise JupyterError('Jupyter created a kernel without a valid ID') from None
        return kernel_id

    def delete_kernel(self, kernel_id):
        # A lost DELETE reply may mean the kernel was already removed. Retry
        # this known ID only, and treat 404 as a successful idempotent cleanup.
        for attempt in range(3):
            try:
                self.request('DELETE', 'api/kernels/' + quote(kernel_id),
                             max_bytes=1024, expected=(200, 204))
                return
            except JupyterError as exc:
                if str(exc).startswith('HTTP 404 '):
                    return
                if attempt == 2:
                    raise
                time.sleep(.25 * (attempt + 1))

    def connect_channels(self, kernel_id, session_id, connect_timeout):
        endpoint = 'api/kernels/' + quote(kernel_id) + '/channels?' + urlencode({'session_id': session_id})
        return self.websocket(endpoint, connect_timeout, 'could not connect to the new kernel WebSocket')

    def connect_terminal(self, name, connect_timeout):
        return self.websocket('terminals/websocket/' + quote(name), connect_timeout, 'could not connect to the new terminal WebSocket')

    def websocket(self, endpoint, connect_timeout, failure):
        try:
            import websocket
        except ImportError:
            raise JupyterError('websocket-client is required (import websocket)') from None
        parsed = urlsplit(self.url(endpoint))
        scheme = 'wss' if parsed.scheme == 'https' else 'ws'
        ws_url = urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, ''))
        cookie_request = Request(self.url(endpoint))
        self.cookies.add_cookie_header(cookie_request)
        cookie_header = cookie_request.get_header('Cookie')
        if not cookie_header:
            raise JupyterError('Jupyter authentication cookie is unavailable for WebSocket')
        headers = ['Cookie: ' + cookie_header]
        token = self.xsrf_cookie()
        if token:
            headers.append('X-XSRFToken: ' + token)
        deadline = time.monotonic() + connect_timeout
        while True:
            try:
                return websocket.create_connection(ws_url, timeout=min(5, connect_timeout), header=headers, origin=self.origin,http_no_proxy=[urlsplit(self.base_url).hostname])
            except websocket.WebSocketBadStatusException as exc:
                if exc.status_code in (401, 403, 404):
                    raise JupyterError(f'WebSocket rejected with HTTP {exc.status_code}') from None
            except (websocket.WebSocketException, OSError):
                pass
            if time.monotonic() >= deadline:
                raise JupyterError(failure)
            time.sleep(0.5)

ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07')

def terminal_output(ws, nonce, timeout):
    """Read a Jupyter terminal until `P6R_EXIT_<nonce>=<status>` (returns status, text) or
    `P6R_MISSING_<nonce>` (returns None, text). The nonce appears only in output, never in the echo."""
    done = re.compile('P6R_(EXIT|MISSING)_' + re.escape(nonce) + r'(?:=(\d+))?')
    deadline, text = time.monotonic() + timeout, ''
    while True:
        for line in text.replace('\r', '\n').split('\n')[:-1]:
            found = done.search(line)
            if found:
                return (int(found.group(2)) if found.group(1) == 'EXIT' and found.group(2) else None), text
        if time.monotonic() >= deadline:
            raise TimeoutError('Board terminal timed out')
        ws.settimeout(min(5, max(0.2, deadline - time.monotonic())))
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        try:
            message = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(message, list) and message and message[0] == 'stdout' and len(message) > 1 and isinstance(message[1], str):
            text = (text + message[1])[-2000000:]
        elif isinstance(message, list) and message and message[0] == 'disconnect':
            raise ConnectionError('Board terminal closed before the command finished: ' + ANSI.sub('', text)[-2000:])

def terminal_result(text, status):
    """The last __REVIEW_RESULT__ line of a finished terminal command, as execute_code returns it."""
    lines = ANSI.sub('', text).replace('\r', '\n').split('\n')
    if status != 0:
        raise RuntimeError('Board execution failed (exit %d): ' % status + '\n'.join(l for l in lines if l.strip())[-4000:])
    for line in reversed(lines):
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX):])
    raise RuntimeError('Board execution returned no result')

def execute_code(ws, code, timeout):
    message_id = uuid.uuid4().hex
    packet = {'channel': 'shell', 'header': {'msg_id': message_id, 'username': 'pynq_review', 'session': uuid.uuid4().hex, 'date': datetime.now(timezone.utc).isoformat(), 'msg_type': 'execute_request', 'version': '5.3'}, 'parent_header': {}, 'metadata': {}, 'content': {'code': code, 'silent': False, 'store_history': False, 'user_expressions': {}, 'allow_stdin': False, 'stop_on_error': True}}
    ws.send(json.dumps(packet))
    deadline, reply, idle, streams, errors = (time.monotonic() + timeout, None, False, '', [])
    while not (reply is not None and idle):
        if time.monotonic() >= deadline:
            raise TimeoutError('Board kernel timed out')
        ws.settimeout(min(5, max(0.2, deadline - time.monotonic())))
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        if not raw:
            raise RuntimeError('Board WebSocket closed')
        data = json.loads(raw)
        if data.get('parent_header', {}).get('msg_id') != message_id:
            continue
        content = data.get('content', {})
        msg_type = data.get('msg_type') or data.get('header', {}).get('msg_type')
        if msg_type == 'execute_reply':
            reply = content.get('status')
        elif msg_type == 'status' and content.get('execution_state') == 'idle':
            idle = True
        elif msg_type == 'stream':
            streams = (streams + content.get('text', ''))[-2000000:]
        elif msg_type == 'error':
            errors.append(content.get('evalue', 'Board kernel exception'))
    if reply != 'ok':
        raise RuntimeError('Board execution failed: ' + '; '.join(errors))
    for line in reversed(streams.splitlines()):
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX):])
    raise RuntimeError('Board execution returned no result')
