"""Offline connection diagnostics: preserve useful causes, never credentials."""
import unittest
from unittest.mock import patch
from urllib.error import URLError, HTTPError

from jupyter_link import JupyterClient, JupyterError, network_error_detail


class ConnectionDiagnostics(unittest.TestCase):
    def test_real_windows_access_denial_is_explained_without_secret_reason(self):
        reason=PermissionError(13,'private-url-password-cookie')
        reason.winerror=10013
        client=JupyterClient('http://192.168.2.99:9090',1)
        with patch.object(client.opener,'open',side_effect=URLError(reason)):
            with self.assertRaises(JupyterError) as result:
                client.request('POST','login',data=b'password=secret',content_type='application/x-www-form-urlencoded')
        text=str(result.exception)
        self.assertIn('10013',text)
        self.assertIn('VPN',text)
        for sensitive in ('private-url','password','cookie','secret'):
            self.assertNotIn(sensitive,text)

    def test_missing_route_and_refused_service_have_different_actions(self):
        self.assertIn('IP 网段',network_error_detail(OSError(101,'unreachable')))
        self.assertIn('Jupyter 服务',network_error_detail(ConnectionRefusedError(111,'refused')))

    def test_timeout_remains_bounded_and_actionable(self):
        text=network_error_detail(URLError(TimeoutError('sensitive request body')))
        self.assertIn('超时',text)
        self.assertNotIn('sensitive',text)

    def test_unknown_url_error_does_not_echo_embedded_credentials(self):
        text=network_error_detail(URLError('http://name:password@host/?token=private'))
        self.assertNotIn('password',text)
        self.assertNotIn('private',text)

    def test_http_auth_failure_keeps_existing_behavior(self):
        client=JupyterClient('http://192.168.2.99:9090',1)
        with patch.object(client.opener,'open',side_effect=HTTPError('secret-url',403,'private',{},None)):
            with self.assertRaisesRegex(JupyterError,'HTTP 403 for GET api/kernelspecs'):
                client.request('GET','api/kernelspecs')


if __name__=='__main__':unittest.main()
