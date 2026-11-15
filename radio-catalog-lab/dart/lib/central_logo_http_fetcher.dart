// Opt-in-only transport for SHA-verified central logo objects.
// Not connected to LogoLibraryService or the existing V64 startup path.
import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'central_radio_catalog_core.dart';

/// Validates exact body size while streaming: never buffer an unbounded image.
/// The signed catalog supplies [expectedBytes]; the Flutter image decoder
/// independently verifies SHA-256, MIME magic bytes and dimensions.
Future<Uint8List> readExactCentralLogoBytes(
  Stream<List<int>> body,
  int expectedBytes, {
  Duration idleTimeout = const Duration(seconds: 15),
}) async {
  if (expectedBytes < 1 || expectedBytes > 8 * 1024 * 1024) {
    throw const CentralCatalogException('Invalid expected logo byte count');
  }
  final builder = BytesBuilder(copy: false);
  await for (final chunk in body.timeout(idleTimeout)) {
    if (chunk.length > expectedBytes - builder.length) {
      throw const CentralCatalogException('Central logo exceeds signed byte count');
    }
    builder.add(chunk);
  }
  if (builder.length != expectedBytes) {
    throw const CentralCatalogException('Truncated central logo transfer');
  }
  return builder.takeBytes();
}

/// Strictly HTTPS, no credentials, fragments, numeric addresses or local
/// hostnames. This does not replace DNS/rebinding defenses at a publisher.
bool isSafeCentralLogoUrl(Uri uri) {
  if (uri.scheme != 'https' || !uri.hasAuthority || uri.userInfo.isNotEmpty ||
      uri.hasFragment || uri.host.isEmpty) {
    return false;
  }
  final lowerHost = uri.host.toLowerCase();
  final host = lowerHost.endsWith('.')
      ? lowerHost.substring(0, lowerHost.length - 1)
      : lowerHost;
  if (host == 'localhost' || host.endsWith('.localhost') ||
      host.endsWith('.local') || host.endsWith('.internal') ||
      !host.contains('.') || host.contains(':') ||
      RegExp(r'^[0-9.]+$').hasMatch(host)) {
    return false;
  }
  return true;
}

class CentralLogoHttpFetcher {
  const CentralLogoHttpFetcher();

  Future<Uint8List> fetch(Uri url, int expectedBytes) async {
    if (!isSafeCentralLogoUrl(url)) {
      throw const CentralCatalogException('Unsafe central logo transport URL');
    }
    if (expectedBytes < 1 || expectedBytes > 8 * 1024 * 1024) {
      throw const CentralCatalogException('Invalid expected logo byte count');
    }

    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10)
      ..autoUncompress = false;
    try {
      final request = await client.getUrl(url).timeout(
        const Duration(seconds: 15),
      );
      request.followRedirects = false;
      request.headers.set(HttpHeaders.acceptHeader, 'image/png,image/jpeg,image/webp');
      // The object must be transferred byte-for-byte as signed.
      request.headers.set(HttpHeaders.acceptEncodingHeader, 'identity');
      final response = await request.close().timeout(
        const Duration(seconds: 20),
      );
      if (response.statusCode != HttpStatus.ok) {
        throw CentralCatalogException(
          'Central logo HTTP status ${response.statusCode}',
        );
      }
      if (response.contentLength > expectedBytes) {
        throw const CentralCatalogException('Oversized central logo response');
      }
      final mime = response.headers.contentType?.mimeType.toLowerCase();
      if (mime != null &&
          mime != 'image/png' && mime != 'image/jpeg' && mime != 'image/webp') {
        throw const CentralCatalogException('Unexpected logo HTTP content type');
      }
      return await readExactCentralLogoBytes(response, expectedBytes);
    } finally {
      client.close(force: true);
    }
  }
}
