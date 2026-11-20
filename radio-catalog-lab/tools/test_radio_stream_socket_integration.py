"""End-to-end socket tests with a LOCAL fake radio server.

No outgoing network: the resolver reports one *synthetic public* IP, but
the patched socket factory connects only to this test's ephemeral loopback
fixture. The production validator still rejects loopback and private DNS.
"""
import socket
import threading
import unittest
from unittest.mock import patch

from radio_stream_technical_probe import PinnedHttpTransport, probe_url


def exercise_routes(routes, callback):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(3)
    server.settimeout(4)
    port = server.getsockname()[1]
    seen = []
    errors = []

    def handle():
        try:
            for _ in range(len(routes)):
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(4)
                    raw = bytearray()
                    while b"\r\n\r\n" not in raw and len(raw) < 8192:
                        packet = connection.recv(4096)
                        if not packet:
                            break
                        raw.extend(packet)
                    first = bytes(raw).split(b"\r\n", 1)[0]
                    seen.append(first.decode("ascii", "replace"))
                    path = first.split()[1].decode("ascii")
                    connection.sendall(routes[path])
        except Exception as error:
            errors.append(str(error))
        finally:
            server.close()

    worker = threading.Thread(target=handle, daemon=True)
    worker.start()
    original_socket_connect = socket.create_connection

    def resolver(host, requested_port, **kwargs):
        assert host == "radio.example.org", host
        assert requested_port == port
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

    def checked_test_connect(address, timeout=None, source_address=None):
        # Public-IP pinning is exercised, but never connects to 8.8.8.8.
        assert address == ("8.8.8.8", port), address
        return original_socket_connect(("127.0.0.1", port), timeout=timeout)

    with patch("radio_stream_technical_probe.socket.create_connection",
               side_effect=checked_test_connect):
        try:
            transport = PinnedHttpTransport(resolver=resolver)
            value = callback(transport.request, port)
        finally:
            worker.join(timeout=5)
    if worker.is_alive() or errors:
        raise AssertionError("Fixture did not complete: " + repr(errors))
    return value, seen


class SocketIntegrationTests(unittest.TestCase):
    def test_legacy_icy_status_stream_works_over_real_socket(self):
        response = (b"ICY 200 OK\r\nContent-Type: audio/mpeg\r\n"
                    b"icy-name: Test Metal Radio\r\n\r\nID3\x04\x00\x00" + b"\0"*60)
        out, requests = exercise_routes(
            {"/live": response},
            lambda call, port: probe_url(f"http://radio.example.org:{port}/live", call))
        self.assertEqual(out["verdict"], "audio_sample_ok")
        self.assertEqual(out["formatHint"], "mp3_id3")
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0].startswith("GET /live HTTP/1.1"))

    def test_real_socket_m3u_one_hop_then_icy_audio(self):
        routes = {
            "/playlist.m3u": (
                b"HTTP/1.1 200 OK\r\nContent-Type: audio/x-mpegurl\r\n"
                b"Connection: close\r\n\r\n#EXTM3U\n/live\n"
            ),
            "/live": (
                b"ICY 200 OK\r\nContent-Type: audio/mpeg\r\n"
                b"\r\nID3\x04\x00\x00" + b"\0"*60
            ),
        }
        out, requests = exercise_routes(
            routes,
            lambda call, port: probe_url(
                f"http://radio.example.org:{port}/playlist.m3u", call))
        self.assertEqual(out["verdict"], "audio_sample_ok")
        self.assertEqual(out["redirectCount"], 1)
        self.assertEqual(len(requests), 2)
        self.assertTrue(requests[1].startswith("GET /live HTTP/1.1"))

    def test_real_socket_hls_is_pending_without_segment_request(self):
        data = (b"HTTP/1.1 200 OK\r\nContent-Type: application/vnd.apple.mpegurl\r\n"
                b"Connection: close\r\n\r\n#EXTM3U\n"
                b"#EXT-X-TARGETDURATION:3\n#EXTINF:3,\n"
                b"http://127.0.0.1/private.ts\n")
        out, requests = exercise_routes(
            {"/live.m3u8": data},
            lambda call, port: probe_url(
                f"http://radio.example.org:{port}/live.m3u8", call))
        self.assertEqual(out["verdict"], "playlist_pending")
        self.assertEqual(out["reason"], "hls_manifest_pending")
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
