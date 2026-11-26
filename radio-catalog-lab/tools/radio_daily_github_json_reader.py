"""Explicit read-only HTTPS client for the laboratory GitHub Data API.

No token discovery, write methods, redirects, proxies or default invocation.
A token, if supplied, must be scoped independently to read-only access.
"""
import http.client
import re
import socket
import ssl
import time

from radio_daily_baseline_verify import strict_json
from radio_daily_github_readback import API
from radio_daily_git_lab_transport import REF
from radio_stream_technical_probe import public_resolved_ips

HOST = "api.github.com"
BASE = "/repos/Sarogal/Ondes-Catalogues"
REF_PATH = BASE + "/git/ref/" + REF.removeprefix("refs/")
OBJECT = re.compile(re.escape(BASE)+r"/git/(?:commits|trees|blobs)/[a-f0-9]{40}")
DEPLOYMENT = re.compile(re.escape(BASE)+r"/deployments/[1-9][0-9]*(?:/statuses)?")
MAX_RESPONSE = 22 * 1024 * 1024
MAX_TOTAL = 384 * 1024 * 1024


class GitHubJSONReader:
    def __init__(self, *, token=None, max_calls=None, max_seconds=300,
                 resolver=socket.getaddrinfo, clock=time.monotonic):
        if token is not None and (not isinstance(token,str)
                or not re.fullmatch(r"[A-Za-z0-9_]{1,512}",token)):
            raise ValueError("invalid explicit read credential")
        ceiling = 1000 if token else 30
        max_calls = ceiling if max_calls is None else max_calls
        if (type(max_calls) is not int or not 1 <= max_calls <= ceiling
                or not 0 < max_seconds <= 600):
            raise ValueError("invalid GitHub read budget")
        self._token = token
        self._max_calls, self._clock = max_calls, clock
        self._deadline = clock()+max_seconds
        self._resolver = resolver
        self.calls = self._bytes = 0
        self._repo_verified = False
        self._rate_exhausted = False
        self.diagnostic = "not_started"

    def _remaining(self):
        left = self._deadline-self._clock()
        if left <= 0:
            raise ValueError("GitHub read deadline")
        return min(12,left)

    def _get(self,path,limit):
        self._remaining()
        if self.calls >= self._max_calls or self._rate_exhausted:
            raise ValueError("GitHub API budget exhausted")
        if type(limit) is not int or not 0 < limit <= MAX_RESPONSE or self._bytes+limit > MAX_TOTAL:
            raise ValueError("invalid GitHub response budget")
        self.calls += 1
        self.diagnostic = "dns_check"
        ip = public_resolved_ips(HOST,443,self._resolver)[0]
        self.diagnostic = "https_connect"
        conn = http.client.HTTPSConnection(HOST,443,timeout=self._remaining(),
                                            context=ssl.create_default_context())
        def connect(address,timeout=None,source_address=None):
            if address != (HOST,443):
                raise ValueError("unexpected GitHub connection target")
            return socket.create_connection((ip,443),timeout=self._remaining())
        conn._create_connection = connect
        headers = {"Accept":"application/vnd.github+json",
                   "X-GitHub-Api-Version":"2022-11-28",
                   "User-Agent":"GrossesOndes-LabReadback/1.0",
                   "Accept-Encoding":"identity","Connection":"close"}
        if self._token is not None:
            headers["Authorization"] = "Bearer "+self._token
        try:
            conn.request("GET",path,headers=headers)
            response = conn.getresponse()
            self.diagnostic = "http_"+str(response.status) if type(response.status) is int and 100 <= response.status <= 599 else "invalid_http_status"
            if response.getheader("X-RateLimit-Remaining") == "0":
                self._rate_exhausted = True
            if response.status == 404 and path == REF_PATH and self._repo_verified:
                return 404, {}
            if response.status != 200:
                raise ValueError("GitHub API read refused")
            self.diagnostic = "response_representation"
            if (response.getheader("Content-Type","").split(";",1)[0].strip().lower()
                    != "application/json" or response.getheader("Content-Encoding","identity").lower() != "identity"
                    or response.getheader("Content-Range")):
                raise ValueError("unexpected GitHub response representation")
            lengths=response.headers.get_all("Content-Length",[])
            if len(lengths)>1 or (lengths and (not lengths[0].isdecimal()
                    or not 0<int(lengths[0])<=limit)):
                raise ValueError("invalid GitHub content length")
            self.diagnostic = "response_body"
            data=bytearray()
            while True:
                self._remaining()
                chunk=response.read1(min(65536,limit+1-len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                self._bytes += len(chunk)
                if len(data)>limit or self._bytes>MAX_TOTAL:
                    raise ValueError("oversized GitHub response")
            self._remaining()
            if not data or (lengths and len(data)!=int(lengths[0])):
                raise ValueError("truncated GitHub response")
            self.diagnostic = "json_decode"
            parsed = strict_json(bytes(data))
            self.diagnostic = "json_read"
            return 200, parsed
        except (OSError,http.client.HTTPException):
            raise ValueError("GitHub HTTPS transport unavailable") from None
        finally:
            conn.close()

    def __call__(self,url,limit):
        prefix="https://"+HOST
        if not isinstance(url,str) or not url.startswith(prefix+"/"):
            raise ValueError("unauthorized GitHub URL")
        path=url[len(prefix):]
        if path != REF_PATH and not OBJECT.fullmatch(path) and not DEPLOYMENT.fullmatch(path):
            raise ValueError("unauthorized GitHub API path")
        if not self._repo_verified:
            _,repo=self._get(BASE,65536)
            if (not isinstance(repo,dict) or repo.get("full_name")!="Sarogal/Ondes-Catalogues"
                    or repo.get("private") is not False
                    or repo.get("id") != 1438875064):
                self.diagnostic = "repository_identity"
                raise ValueError("GitHub repository identity mismatch")
            self._repo_verified=True
        return self._get(path,limit)
