import json
import unittest
from email.message import Message
from unittest.mock import Mock, patch

from radio_daily_github_json_reader import GitHubJSONReader, BASE, REF_PATH, HOST
from radio_daily_github_readback import GitHubReadback
from radio_daily_github_transfer_contract import DESTINATION
from radio_daily_git_lab_transport import REF, ZERO


def resolver(*args,**kwargs):
    return [(2,1,6,"",("93.184.216.34",443))]


def response(doc=None,status=200,remaining=None):
    result=Mock()
    result.status=status
    data=json.dumps(doc if doc is not None else {}).encode()
    headers=Message()
    headers["Content-Type"]="application/json"
    headers["Content-Length"]=str(len(data))
    if remaining is not None:
        headers["X-RateLimit-Remaining"]=remaining
    result.headers=headers
    result.getheader.side_effect=lambda k,d=None:headers.get(k,d)
    result.read1.side_effect=[data,b""]
    return result


class GitHubJSONReaderTests(unittest.TestCase):
    def repo(self):
        return response(dict(full_name="Sarogal/Ondes-Catalogues",private=False))

    @patch("radio_daily_github_json_reader.http.client.HTTPSConnection")
    def test_public_repo_verified_before_missing_ref(self,factory):
        conn=factory.return_value
        conn.getresponse.side_effect=[self.repo(),response(status=404)]
        reader=GitHubJSONReader(resolver=resolver)
        self.assertEqual(GitHubReadback(reader).read_head(DESTINATION,REF),ZERO)
        self.assertEqual([c.args for c in conn.request.call_args_list],[("GET",BASE),("GET",REF_PATH)])
        self.assertNotIn("Authorization",conn.request.call_args.kwargs["headers"])

    @patch("radio_daily_github_json_reader.http.client.HTTPSConnection")
    def test_pinned_read_only_token_and_ref(self,factory):
        conn=factory.return_value
        conn.getresponse.side_effect=[self.repo(),response(dict(ref=REF,object=dict(type="commit",sha="a"*40)))]
        reader=GitHubJSONReader(token="synthetic_token",resolver=resolver)
        self.assertEqual(GitHubReadback(reader).read_head(DESTINATION,REF),"a"*40)
        self.assertEqual(conn.request.call_args.kwargs["headers"]["Authorization"],"Bearer synthetic_token")
        with patch("radio_daily_github_json_reader.socket.create_connection") as socket:
            conn._create_connection((HOST,443))
            self.assertEqual(socket.call_args.args[0],("93.184.216.34",443))

    @patch("radio_daily_github_json_reader.http.client.HTTPSConnection")
    def test_unapproved_urls_rejected_before_network(self,factory):
        reader=GitHubJSONReader(resolver=resolver)
        for url in ("https://example.org/"+BASE,"https://"+HOST+BASE+"/git/refs/heads/main",
                    "https://"+HOST+BASE+"/git/trees/"+"a"*40+"?recursive=1"):
            with self.assertRaisesRegex(ValueError,"unauthorized"):
                reader(url,100)
        factory.assert_not_called()

    @patch("radio_daily_github_json_reader.http.client.HTTPSConnection")
    def test_wrong_repo_or_rate_limit_held(self,factory):
        conn=factory.return_value
        for repo in (response(dict(full_name="other/repo",private=False)),
                     response(dict(full_name="Sarogal/Ondes-Catalogues",private=False),remaining="0")):
            conn.getresponse.side_effect=[repo]
            reader=GitHubJSONReader(resolver=resolver)
            with self.assertRaises(ValueError):
                GitHubReadback(reader).read_head(DESTINATION,REF)

    @patch("radio_daily_github_json_reader.http.client.HTTPSConnection")
    def test_redirect_and_forbidden_not_absent(self,factory):
        conn=factory.return_value
        for status in (301,403,429,500):
            conn.getresponse.side_effect=[self.repo(),response(status=status)]
            with self.assertRaisesRegex(ValueError,"refused"):
                GitHubReadback(GitHubJSONReader(resolver=resolver)).read_head(DESTINATION,REF)

    @patch("radio_daily_github_json_reader.http.client.HTTPSConnection")
    def test_private_dns_refused_before_tls(self,factory):
        reader=GitHubJSONReader(resolver=lambda *a,**k:[(2,1,6,"",("127.0.0.1",443))])
        with self.assertRaises(ValueError):
            GitHubReadback(reader).read_head(DESTINATION,REF)
        factory.assert_not_called()
