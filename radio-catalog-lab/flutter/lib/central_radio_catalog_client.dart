// Isolated central catalog snapshots and optional fetcher.
// Nothing in the existing V64 app imports or instantiates this service.
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'central_radio_catalog_core.dart';

typedef CentralCatalogByteFetcher = Future<Uint8List> Function(
    Uri uri, int maxBytes);

class CentralCatalogDiskStore {
  const CentralCatalogDiskStore(this.directory);
  final Directory directory;

  static final _snapshotName =
      RegExp(r'^go-radio-v1-([1-9][0-9]*)-([0-9a-f]{64})\.json$');

  Future<ValidatedCentralCatalog?> loadLatest(
      CentralCatalogVerifier verifier) async {
    if (!await directory.exists()) return null;
    final candidates = await directory
        .list(followLinks: false)
        .where((entry) => entry is File)
        .cast<File>()
        .where((file) => _snapshotName.hasMatch(
            file.uri.pathSegments.last))
        .toList();
    candidates.sort((a, b) {
      final am = _snapshotName.firstMatch(a.uri.pathSegments.last)!;
      final bm = _snapshotName.firstMatch(b.uri.pathSegments.last)!;
      final av = int.tryParse(am.group(1)!) ?? 0;
      final bv = int.tryParse(bm.group(1)!) ?? 0;
      return bv.compareTo(av);
    });
    for (final file in candidates) {
      try {
        // Do not read arbitrary-sized or symlinked files as catalog snapshots.
        if (await file.length() > 15 * 1024 * 1024) continue;
        final raw = jsonDecode(await file.readAsString());
        if (raw is! Map<String, dynamic> ||
            raw['pointer_base64'] is! String ||
            raw['catalog_base64'] is! String) continue;
        final pointer = Uint8List.fromList(
            base64.decode(raw['pointer_base64'] as String));
        final catalog = Uint8List.fromList(
            base64.decode(raw['catalog_base64'] as String));
        final verified = await verifier.verify(
            pointerBytes: pointer, catalogBytes: catalog);
        final expected =
            'go-radio-v1-${verified.pointer.sequence}-${verified.pointer.sha256}.json';
        if (file.uri.pathSegments.last != expected) continue;
        return verified;
      } catch (_) {
        // A partial or corrupt newest snapshot must not erase older snapshots.
        continue;
      }
    }
    return null;
  }

  Future<void> persist(ValidatedCentralCatalog snapshot) async {
    await directory.create(recursive: true);
    final filename =
        'go-radio-v1-${snapshot.pointer.sequence}-${snapshot.pointer.sha256}.json';
    final finalFile = File('${directory.path}${Platform.pathSeparator}$filename');
    if (await finalFile.exists()) {
      throw const CentralCatalogException('Snapshot already exists; refusing overwrite');
    }
    final staging = File('${finalFile.path}.pending');
    if (await staging.exists()) {
      throw const CentralCatalogException('Pending snapshot exists; manual inspection required');
    }
    try {
      final payload = jsonEncode({
        'pointer_base64': base64.encode(snapshot.pointerBytes),
        'catalog_base64': base64.encode(snapshot.catalogBytes)
      });
      await staging.writeAsString(payload, flush: true);
      // Final name appears only when the complete, validated data is durable.
      await staging.rename(finalFile.path);
    } catch (_) {
      // Never delete any previously committed snapshot. Pending partial is
      // deliberately left for diagnosis and ignored by loadLatest.
      rethrow;
    }
  }
}

class CentralCatalogHttpFetcher {
  const CentralCatalogHttpFetcher();

  Future<Uint8List> fetch(Uri uri, int maxBytes) async {
    if (uri.scheme != 'https' || uri.userInfo.isNotEmpty ||
        uri.hasFragment || uri.host.isEmpty) {
      throw const CentralCatalogException('Unsafe catalog transport URL');
    }
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
    try {
      final request = await client.getUrl(uri).timeout(
          const Duration(seconds: 15));
      request.followRedirects = false;
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      final response = await request.close().timeout(
          const Duration(seconds: 20));
      if (response.statusCode != HttpStatus.ok) {
        throw CentralCatalogException(
            'Catalog HTTP status ${response.statusCode}');
      }
      if (response.contentLength > maxBytes) {
        throw const CentralCatalogException('Catalog response exceeds limit');
      }
      final builder = BytesBuilder(copy: false);
      await for (final chunk in response.timeout(const Duration(seconds: 20))) {
        builder.add(chunk);
        if (builder.length > maxBytes) {
          throw const CentralCatalogException('Catalog body exceeds limit');
        }
      }
      return builder.takeBytes();
    } finally {
      client.close(force: true);
    }
  }
}

class CentralCatalogSyncResult {
  const CentralCatalogSyncResult(this.snapshot, {required this.updated});
  final ValidatedCentralCatalog snapshot;
  final bool updated;
}

class CentralRadioCatalogClient {
  CentralRadioCatalogClient({
    required Uri baseUri,
    required this.verifier,
    required this.disk,
    CentralCatalogByteFetcher? fetch,
  })  : baseUri = baseUri,
        _fetch = fetch ?? const CentralCatalogHttpFetcher().fetch {
    if (baseUri.scheme != 'https' ||
        baseUri.userInfo.isNotEmpty ||
        baseUri.hasFragment || baseUri.hasQuery ||
        !baseUri.path.endsWith('/') || baseUri.host.isEmpty) {
      throw const CentralCatalogException('Unsafe base catalog URL');
    }
  }

  final Uri baseUri;
  final CentralCatalogVerifier verifier;
  final CentralCatalogDiskStore disk;
  final CentralCatalogByteFetcher _fetch;
  bool _synchronizing = false;

  Future<ValidatedCentralCatalog?> loadOffline() =>
      disk.loadLatest(verifier);

  /// Never called at startup by existing CatalogController. Explicit opt-in
  /// test invocation only until full product/Android Auto authorization.
  Future<CentralCatalogSyncResult> sync() async {
    if (_synchronizing) {
      throw const CentralCatalogException('Concurrent catalog sync');
    }
    _synchronizing = true;
    try {
      final previous = await loadOffline();
      final pointerBytes = await _fetch(
          baseUri.resolve('current.json'),
          CentralCatalogPointer.maximumPointerBytes);
      // Authentication precedes even the immutable catalog HTTP request.
      final pointer = await verifier.verifyPointer(pointerBytes);
      if (previous != null && pointer.sequence <= previous.pointer.sequence) {
        if (pointer.sequence == previous.pointer.sequence &&
            pointer.sha256 == previous.pointer.sha256) {
          return CentralCatalogSyncResult(previous, updated: false);
        }
        throw const CentralCatalogException('Stale or conflicting pointer');
      }
      final payload = await _fetch(
          baseUri.resolve(pointer.path), pointer.length);
      final verified = await verifier.verify(
          pointerBytes: pointerBytes,
          catalogBytes: payload,
          previous: previous);
      await disk.persist(verified);
      return CentralCatalogSyncResult(verified, updated: true);
    } finally {
      _synchronizing = false;
    }
  }
}
