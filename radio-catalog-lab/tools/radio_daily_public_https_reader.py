"""Bounded, read-only HTTPS adapter and GitHub deployment status contract.

No default Pages target, token, write operation, CLI or workflow activation.
URLs and response sizes must be explicitly approved by the caller. The
deployment REST check is distinct from verification of public release bytes.
"""
import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

from radio_daily_baseline_verify import strict_json
from radio_daily_deployment_verify import PublicResponse
from radio_stream_technical_probe import public_resolved_ips, validate_endpoint

MAX_RESOURCE = 10 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
API = "https://api.github.com/repos/Sarogal/Ondes-Catalogues/deployments/"
OID = re.compile(r"[a-f0-9]{40}")


def approved_url(url):
    parsed = validate_endpoint(url)
    if (parsed.scheme != "https" or parsed.port not in (None, 443)
            or parsed.query or not parsed.path.startswith("/")
            or any(ord(c) < 33 or ord(c) > 126 for c in url)
            or "%" in parsed.path or "\\" in parsed.path
            or any(part in (".", "..") for part in parsed.path.split("/"))
            or parsed.netloc != parsed.hostname):
        raise ValueError("unapproved HTTPS resource URL")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return parsed
    raise ValueError("literal IP resource forbidden")


class PublicHTTPSReader:
    def __init__(self, resources, *, resolver=socket.getaddrinfo, clock=time.monotonic,
                 timeout=12, max_seconds=180):
        """resources maps exact independently approved URLs to byte limits."""
        if (not isinstance(resources, dict) or not resources
                or any(type(n) is not int or not 0 < n <= MAX_RESOURCE for n in resources.values())
                or sum(resources.values()) > MAX_TOTAL
                or not 0 < timeout <= 15 or not 0 < max_seconds <= 300):
            raise ValueError("invalid public read budget")
        for url in resources:
            approved_url(url)
        self._resources = dict(resources)
        self._resolver, self._clock = resolver, clock
        self._timeout = timeout
        self._deadline = clock() + max_seconds
        self._calls = {}
        self._bytes = 0

    def _remaining(self):
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise ValueError("public read deadline")
        return min(self._timeout, remaining)

    def __call__(self, url, max_bytes):
        if (url not in self._resources or type(max_bytes) is not int
                or not 0 < max_bytes <= self._resources[url]
                or self._calls.get(url, 0) >= 2
                or self._bytes + max_bytes > MAX_TOTAL):
            raise ValueError("unapproved public read or exhausted budget")
        parsed = approved_url(url)
        self._remaining()
        self._calls[url] = self._calls.get(url, 0) + 1
        host = parsed.hostname
        ip = public_resolved_ips(host, 443, self._resolver)[0]
        connection = http.client.HTTPSConnection(host, 443,
            timeout=self._remaining(), context=ssl.create_default_context())
        def connect_checked(address, timeout=None, source_address=None):
            if address != (host, 443):
                raise ValueError("unexpected public connection target")
            return socket.create_connection((ip, 443), timeout=self._remaining())
        connection._create_connection = connect_checked
        try:
            connection.request("GET", parsed.path, headers={
                "Accept": "application/json,image/png,image/jpeg,image/webp",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": "GrossesOndes-PublicReadback/1.0",
                "Connection": "close",
            })
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("public resource unavailable or redirected")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("unexpected public content encoding")
            if response.getheader("Content-Range"):
                raise ValueError("partial public response refused")
            lengths = response.headers.get_all("Content-Length", [])
            if len(lengths) > 1:
                raise ValueError("ambiguous public response length")
            length = lengths[0] if lengths else None
            if length is not None and (not length.isdecimal() or not 0 < int(length) <= max_bytes):
                raise ValueError("invalid public content length")
            chunks = bytearray()
            while True:
                self._remaining()
                chunk = response.read1(min(65536, max_bytes+1-len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
                self._bytes += len(chunk)
                if len(chunks) > max_bytes or self._bytes > MAX_TOTAL:
                    raise ValueError("oversized public response")
            self._remaining()
            if not chunks or (length is not None and len(chunks) != int(length)):
                raise ValueError("empty or truncated public response")
            return PublicResponse(200, url, response.getheader("Content-Type", ""), bytes(chunks))
        finally:
            connection.close()


def deployment_status(fetch, *, deployment_id, expected_commit, expected_ref, environment):
    """Check one explicitly identified public GitHub REST deployment.

    A success from this API does not establish Pages visibility; public
    resource readback remains mandatory. No actual deployment is requested.
    """
    if (type(deployment_id) is not int or deployment_id <= 0
            or not isinstance(expected_commit, str) or not OID.fullmatch(expected_commit)
            or not isinstance(expected_ref, str) or not expected_ref
            or not isinstance(environment, str) or not environment):
        raise ValueError("explicit deployment anchor required")
    url = API + str(deployment_id)
    def read(endpoint):
        result = fetch(endpoint, 1048576)
        if (not isinstance(result, PublicResponse) or result.status != 200
                or result.effective_url != endpoint
                or result.content_type.split(";",1)[0].strip().lower() != "application/json"
                or not isinstance(result.body, bytes) or not 0 < len(result.body) <= 1048576):
            raise ValueError("invalid deployment API response")
        return strict_json(result.body)
    deployment = read(url)
    if (not isinstance(deployment, dict) or deployment.get("id") != deployment_id
            or deployment.get("sha") != expected_commit
            or deployment.get("ref") != expected_ref
            or deployment.get("environment") != environment
            or deployment.get("statuses_url") != url+"/statuses"):
        raise ValueError("deployment identity mismatch")
    statuses = read(url+"/statuses")
    if not isinstance(statuses, list) or not statuses:
        raise ValueError("deployment status unavailable")
    # GitHub deployment statuses are returned newest first. Fail closed
    # when the newest status is not successful, even if older ones were.
    latest = statuses[0]
    if (not isinstance(latest, dict) or latest.get("deployment_url") != url
            or latest.get("environment") != environment
            or latest.get("state") != "success"):
        raise ValueError("expected deployment has not succeeded")
    return dict(deploymentCommit=expected_commit, deploymentStatus="success",
                deploymentId=deployment_id, publicReadbackRequired=True,
                publicationAllowed=False)
