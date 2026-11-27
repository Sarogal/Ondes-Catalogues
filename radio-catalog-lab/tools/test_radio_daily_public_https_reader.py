"""No-network tests for bounded HTTPS readback and exact deployment identity."""
import json
import unittest
from email.message import Message
from unittest.mock import patch, Mock

from radio_daily_public_https_reader import PublicHTTPSReader, approved_url, deployment_status, API
from radio_daily_deployment_verify import PublicResponse

URL="https://catalog.example.org/radio/pointer.json"
COMMIT="a"*40
DEPLOY=API+"123"


def resolver(host, port, **kw):
    return [(2,1,6,"",("93.184.216.34",port))]


class PublicReaderTests(unittest.TestCase):
    def response(self, *, status=200, data=b"{}", length=None, encoding=None):
        response = Mock()
        response.status = status
        headers = Message()
        headers["Content-Type"]="application/json"
        if length is not None:
            headers["Content-Length"]=str(length)
        if encoding:
            headers["Content-Encoding"]=encoding
        response.headers=headers
        response.getheader.side_effect=lambda k,d=None:headers.get(k,d)
        response.read1.side_effect=[data,b""]
        return response

    @patch("radio_daily_public_https_reader.http.client.HTTPSConnection")
    def test_exact_public_read_and_pinned_socket(self, factory):
        conn=factory.return_value
        conn.getresponse.return_value=self.response(length=2)
        reader=PublicHTTPSReader({URL:2},resolver=resolver)
        result=reader(URL,2)
        self.assertEqual(result,PublicResponse(200,URL,"application/json",b"{}"))
        self.assertEqual(conn.request.call_args.args,("GET","/radio/pointer.json"))
        self.assertNotIn("Authorization",conn.request.call_args.kwargs["headers"])
        with patch("radio_daily_public_https_reader.socket.create_connection") as socket:
            conn._create_connection(("catalog.example.org",443))
            self.assertEqual(socket.call_args.args[0],("93.184.216.34",443))
            with self.assertRaisesRegex(ValueError,"unexpected"):
                conn._create_connection(("other.example.org",443))
        conn.close.assert_called_once()

    @patch("radio_daily_public_https_reader.http.client.HTTPSConnection")
    def test_redirect_oversize_truncated_and_compressed_refused(self,factory):
        for response,reason in ((self.response(status=302),"redirected"),
            (self.response(data=b"abc"),"oversized"),(self.response(data=b"x",length=2),"truncated"),
            (self.response(encoding="gzip"),"encoding"),
            (self.response(length=3),"content length")):
            with self.subTest(reason=reason):
                factory.return_value.getresponse.return_value=response
                with self.assertRaisesRegex(ValueError,reason):
                    PublicHTTPSReader({URL:2},resolver=resolver)(URL,2)

    @patch("radio_daily_public_https_reader.http.client.HTTPSConnection")
    def test_unapproved_url_and_private_dns_before_connection(self,factory):
        reader=PublicHTTPSReader({URL:2},resolver=lambda *a,**kw:[(2,1,6,"",("127.0.0.1",443))])
        with self.assertRaisesRegex(ValueError,"unapproved"):
            reader(URL+"x",2)
        with self.assertRaises(ValueError):
            reader(URL,2)
        factory.assert_not_called()

    def test_unsafe_urls_refused(self):
        for url in ("http://catalog.example.org/a","https://catalog.example.org/a?token=secret",
            "https://catalog.example.org/a/../b","https://catalog.example.org/%2e%2e/a",
            "https://93.184.216.34/a","https://user@catalog.example.org/a"):
            with self.subTest(url=url),self.assertRaises(ValueError):
                approved_url(url)

    @patch("radio_daily_public_https_reader.http.client.HTTPSConnection")
    def test_repeated_reads_and_limits(self,factory):
        reader=PublicHTTPSReader({URL:2},resolver=resolver)
        for _ in range(2):
            factory.return_value.getresponse.return_value=self.response(length=2)
            reader(URL,2)
        with self.assertRaisesRegex(ValueError,"budget"):
            reader(URL,2)

    def test_expired_deadline_refused(self):
        tick=iter((0,181))
        reader=PublicHTTPSReader({URL:2},resolver=resolver,clock=lambda:next(tick))
        with self.assertRaisesRegex(ValueError,"deadline"):
            reader(URL,2)


class DeploymentStatusTests(unittest.TestCase):
    def setUp(self):
        self.doc=dict(id=123,sha=COMMIT,ref="radio-lab",environment="github-pages",
                      statuses_url=DEPLOY+"/statuses")
        self.status=[dict(state="success",deployment_url=DEPLOY,environment="github-pages")]
        self.calls=[]

    def fetch(self,url,limit):
        self.calls.append(url)
        data=self.doc if url==DEPLOY else self.status
        return PublicResponse(200,url,"application/json",json.dumps(data).encode())

    def check(self):
        return deployment_status(self.fetch,deployment_id=123,expected_commit=COMMIT,
            expected_ref="radio-lab",environment="github-pages")

    def test_success_still_requires_readback(self):
        result=self.check()
        self.assertEqual(result["deploymentCommit"],COMMIT)
        self.assertTrue(result["publicReadbackRequired"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(self.calls,[DEPLOY,DEPLOY+"/statuses"])

    def test_wrong_commit_ref_or_environment_refused(self):
        for key,value in (("sha","b"*40),("ref","main"),("environment","production")):
            old=self.doc[key]
            self.doc[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,"identity mismatch"):
                self.check()
            self.doc[key]=old

    def test_latest_failure_overrides_old_success(self):
        self.status.insert(0,dict(state="failure",deployment_url=DEPLOY,environment="github-pages"))
        with self.assertRaisesRegex(ValueError,"not succeeded"):
            self.check()
