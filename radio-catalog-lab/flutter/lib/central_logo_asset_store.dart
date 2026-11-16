// Experimental SHA-256 image-object store. Never used by V64's logo loader.
// Downloads are explicit and decoders are injected (no implicit networking).
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;

import 'central_radio_catalog_core.dart';

typedef CentralLogoBytesFetcher = Future<Uint8List> Function(
    Uri url, int maxBytes);
typedef CentralLogoBytesDecoder = Future<CentralDecodedLogo> Function(
    Uint8List bytes);

class CentralDecodedLogo {
  const CentralDecodedLogo({
    required this.width,
    required this.height,
    required this.mimeType,
  });
  final int width;
  final int height;
  final String mimeType;
}

class CentralLogoDescriptor {
  CentralLogoDescriptor({
    required this.sha256,
    required this.byteSize,
    required this.revision,
    required this.url,
    required this.width,
    required this.height,
    required this.mimeType,
  }) {
    final uri = Uri.tryParse(url);
    if (!RegExp(r'^[a-f0-9]{64}$').hasMatch(sha256) ||
        byteSize < 1 || byteSize > 8 * 1024 * 1024 ||
        revision < 1 || width < 1 || width > 10000 ||
        height < 1 || height > 10000 ||
        !{'image/png', 'image/jpeg', 'image/webp'}.contains(mimeType) ||
        uri == null || uri.scheme != 'https' || uri.host.isEmpty ||
        uri.userInfo.isNotEmpty || uri.hasFragment) {
      throw const CentralCatalogException('Invalid signed image descriptor');
    }
  }

  final String sha256;
  final int byteSize;
  final int revision;
  final String url;
  final int width;
  final int height;
  final String mimeType;

  static CentralLogoDescriptor? fromSignedStation(Map<String, dynamic> station) {
    final raw = station['logo'];
    if (raw == null) return null;
    if (raw is! Map<String, dynamic>) {
      throw const CentralCatalogException('Invalid signed station logo');
    }
    final digest = raw['sha256'];
    if (digest is! String || raw['asset_id'] != 'sha256:$digest') {
      throw const CentralCatalogException('Logo asset ID mismatch');
    }
    return CentralLogoDescriptor(
      sha256: digest,
      byteSize: raw['byte_size'] as int,
      revision: raw['revision'] as int,
      url: raw['url'] as String,
      width: raw['width'] as int,
      height: raw['height'] as int,
      mimeType: raw['mime_type'] as String,
    );
  }
}

enum CentralLogoCacheStatus {
  cacheHit,
  downloaded,
  offline,
  retryDeferred,
  downloadRejected,
}

class CentralLogoCacheResult {
  const CentralLogoCacheResult({
    required this.status,
    required this.image,
    required this.usedOlderLogo,
  });
  final CentralLogoCacheStatus status;
  final File? image;
  final bool usedOlderLogo;
  bool get available => image != null;
}

class CentralLogoAssetStore {
  CentralLogoAssetStore({
    required this.directory,
    required this.decoder,
    DateTime Function()? clock,
    this.failedDownloadBackoff = const Duration(hours: 6),
  }) : _clock = clock ?? DateTime.now;

  final Directory directory;
  final CentralLogoBytesDecoder decoder;
  final DateTime Function() _clock;
  final Duration failedDownloadBackoff;
  final Map<String, Future<CentralLogoCacheResult>> _inFlight = {};
  final Map<String, Future<File?>> _importsInFlight = {};

  File _image(CentralLogoDescriptor spec) =>
      File('${directory.path}${Platform.pathSeparator}${spec.sha256}.img');

  File _retryMarker(CentralLogoDescriptor spec) =>
      File('${directory.path}${Platform.pathSeparator}${spec.sha256}.retry.json');

  /// Disk-only. Validates exact SHA/length and the injected image decoder.
  /// Does not open a socket, alter an existing image, or delete any other SHA.
  Future<File?> findVerified(CentralLogoDescriptor spec) async {
    final file = _image(spec);
    if (!await file.exists()) return null;
    try {
      if (await file.length() != spec.byteSize) return null;
      final data = await file.readAsBytes();
      if (crypto.sha256.convert(data).toString() != spec.sha256) return null;
      final decoded = await decoder(data);
      if (decoded.width != spec.width || decoded.height != spec.height ||
          decoded.mimeType != spec.mimeType) return null;
      return file;
    } catch (_) {
      return null;
    }
  }

  /// Optional, network-free migration from an existing URL-keyed V64 logo.
  /// The source is read only, and is NEVER moved or removed. A copied object
  /// is activated only when SHA, exact byte count and decoded image all match
  /// the signed central descriptor. The old cache remains the rollback source.
  ///
  /// A corrupt or competing destination is not overwritten by this importer:
  /// the explicit central updater can repair it separately.
  Future<File?> importVerifiedLegacyFile({
    required CentralLogoDescriptor target,
    required File source,
  }) {
    // Capture the first operation synchronously, before the first async I/O.
    // An import started after an explicit download must not compete with it.
    final currentImport = _importsInFlight[target.sha256];
    if (currentImport != null) return currentImport;
    final download = _inFlight[target.sha256];
    if (download != null) {
      return download.then((_) => findVerified(target));
    }

    final task = _importVerifiedLegacyFile(target: target, source: source);
    _importsInFlight[target.sha256] = task;
    return task.whenComplete(() {
      _importsInFlight.remove(target.sha256);
    });
  }

  Future<File?> _importVerifiedLegacyFile({
    required CentralLogoDescriptor target,
    required File source,
  }) async {
    final cached = await findVerified(target);
    if (cached != null) return cached;
    File? temporary;
    try {
      if (!await source.exists() || await source.length() != target.byteSize) {
        return null;
      }
      final bytes = await source.readAsBytes();
      if (bytes.length != target.byteSize ||
          crypto.sha256.convert(bytes).toString() != target.sha256) {
        return null;
      }
      final decoded = await decoder(bytes);
      if (decoded.width != target.width ||
          decoded.height != target.height ||
          decoded.mimeType != target.mimeType) {
        return null;
      }

      await directory.create(recursive: true);
      final destination = _image(target);
      if (await destination.exists()) return null;
      temporary = File(
        '${destination.path}.pending.legacy.$pid.${_clock().microsecondsSinceEpoch}',
      );
      await temporary.create(exclusive: true);
      await temporary.writeAsBytes(bytes, flush: true);
      if (await destination.exists()) {
        return await findVerified(target);
      }
      await temporary.rename(destination.path);
      return await findVerified(target);
    } catch (_) {
      return null;
    } finally {
      if (temporary != null) {
        try {
          if (await temporary.exists()) await temporary.delete();
        } catch (_) {
          // The original legacy cache is untouched even after I/O failures.
        }
      }
    }
  }

  Future<CentralLogoCacheResult> ensure({
    required CentralLogoDescriptor target,
    CentralLogoDescriptor? previous,
    CentralLogoBytesFetcher? fetch,
  }) {
    final existing = _inFlight[target.sha256];
    if (existing != null) return existing;
    final pending = _ensure(target: target, previous: previous, fetch: fetch);
    _inFlight[target.sha256] = pending;
    return pending.whenComplete(() {
      _inFlight.remove(target.sha256);
    });
  }

  Future<CentralLogoCacheResult> _ensure({
    required CentralLogoDescriptor target,
    required CentralLogoDescriptor? previous,
    required CentralLogoBytesFetcher? fetch,
  }) async {
    // If a verified V64 copy is already being installed, let it finish
    // before deciding whether an HTTP request is necessary.
    final importing = _importsInFlight[target.sha256];
    if (importing != null) await importing;
    final cached = await findVerified(target);
    if (cached != null) {
      return CentralLogoCacheResult(
          status: CentralLogoCacheStatus.cacheHit,
          image: cached,
          usedOlderLogo: false);
    }
    final older = previous == null || previous.sha256 == target.sha256
        ? null : await findVerified(previous);
    final fallback = older != null;

    if (fetch == null) {
      return CentralLogoCacheResult(
          status: CentralLogoCacheStatus.offline,
          image: older, usedOlderLogo: fallback);
    }
    if (await _retryStillActive(target)) {
      return CentralLogoCacheResult(
          status: CentralLogoCacheStatus.retryDeferred,
          image: older, usedOlderLogo: fallback);
    }

    try {
      final bytes = await fetch(Uri.parse(target.url), target.byteSize);
      if (bytes.length != target.byteSize ||
          crypto.sha256.convert(bytes).toString() != target.sha256) {
        throw const CentralCatalogException('Logo SHA or byte count mismatch');
      }
      final decoded = await decoder(bytes);
      if (decoded.width != target.width || decoded.height != target.height ||
          decoded.mimeType != target.mimeType) {
        throw const CentralCatalogException('Logo decode/dimension mismatch');
      }
      await directory.create(recursive: true);
      final output = _image(target);

      // Another store may have finished the identical immutable asset.
      final winner = await findVerified(target);
      if (winner != null) {
        return CentralLogoCacheResult(
            status: CentralLogoCacheStatus.cacheHit,
            image: winner, usedOlderLogo: false);
      }
      if (await output.exists()) {
        // The canonical filename contains invalid bytes. Preserve a forensic
        // copy, but do not let corruption permanently block verified repair.
        final rejected = File('${output.path}.invalid.${pid}.${_clock().microsecondsSinceEpoch}');
        await output.rename(rejected.path);
      }

      final temp = File('${output.path}.pending.${pid}.${_clock().microsecondsSinceEpoch}');
      try {
        await temp.create(exclusive: true);
        await temp.writeAsBytes(bytes, flush: true);
        if (await output.exists()) {
          throw const CentralCatalogException('Concurrent image installation');
        }
        await temp.rename(output.path);
      } finally {
        if (await temp.exists()) await temp.delete();
      }
      return CentralLogoCacheResult(
          status: CentralLogoCacheStatus.downloaded,
          image: output, usedOlderLogo: false);
    } catch (_) {
      // A checksum, decoder or transport failure must never destroy a
      // previously verified object. Suppress repeated boot attempts.
      await _recordFailure(target);
      return CentralLogoCacheResult(
          status: CentralLogoCacheStatus.downloadRejected,
          image: older, usedOlderLogo: fallback);
    }
  }

  Future<bool> _retryStillActive(CentralLogoDescriptor target) async {
    try {
      final marker = _retryMarker(target);
      if (!await marker.exists()) return false;
      if (await marker.length() > 512) return false;
      final decoded = jsonDecode(await marker.readAsString());
      if (decoded is! Map<String, dynamic> ||
          decoded['sha256'] != target.sha256 ||
          decoded['retry_after'] is! String) return false;
      final until = DateTime.tryParse(decoded['retry_after'] as String);
      return until != null && until.isAfter(_clock());
    } catch (_) {
      return false;
    }
  }

  Future<void> _recordFailure(CentralLogoDescriptor target) async {
    try {
      await directory.create(recursive: true);
      final next = _clock().add(failedDownloadBackoff).toUtc().toIso8601String();
      await _retryMarker(target).writeAsString(
        jsonEncode({'sha256': target.sha256, 'retry_after': next}),
        flush: true,
      );
    } catch (_) {
      // The caller still receives a safe older image or an empty fallback.
    }
  }
}
