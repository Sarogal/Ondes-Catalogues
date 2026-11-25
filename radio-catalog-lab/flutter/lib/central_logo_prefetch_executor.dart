// Opt-in-only execution of a SHA-deduplicated plan on an isolated store.
// Nothing in the installed V64 app constructs or calls this class.
// Default is offline; real networking requires both a call-site flag and a
// strict hostname allowlist. No automatic boot, audio or UI integration.
import 'dart:io';

import 'central_logo_asset_store.dart';
import 'central_logo_http_fetcher.dart';
import 'central_logo_preparation_plan.dart';
import 'central_radio_catalog_core.dart';

enum CentralLogoPrefetchOutcome {
  cached,
  offline,
  hostBlocked,
  budgetExceeded,
  downloaded,
  retryDeferred,
  rejected,
}

class CentralLogoPrefetchPolicy {
  CentralLogoPrefetchPolicy({
    this.allowNetwork = false,
    Set<String> allowedHosts = const <String>{},
    this.maxObjects = 12,
    this.maxBytes = 8 * 1024 * 1024,
    this.maxConcurrent = 1,
    this.maxNetworkDuration,
  }) : allowedHosts = Set<String>.unmodifiable(
          allowedHosts.map((host) => host.toLowerCase()),
        ) {
    if (maxObjects < 0 || maxBytes < 0 ||
        maxConcurrent < 1 || maxConcurrent > 8) {
      throw const CentralCatalogException('Invalid prefetch budget');
    }
    if (allowNetwork) {
      if (this.allowedHosts.isEmpty) {
        throw const CentralCatalogException(
          'Network prefetch needs an explicit host allowlist',
        );
      }
      for (final host in this.allowedHosts) {
        final uri = Uri.tryParse('https://$host/');
        if (uri == null ||
            uri.host != host ||
            !isSafeCentralLogoUrl(uri) ||
            uri.port != 443 ||
            uri.path != '/') {
          throw const CentralCatalogException('Invalid allowed image host');
        }
      }
    }
  }

  final bool allowNetwork;
  final Set<String> allowedHosts;
  final int maxObjects;
  final int maxBytes;
  final int maxConcurrent;
  final Duration? maxNetworkDuration;
}

class CentralLogoPrefetchEntry {
  const CentralLogoPrefetchEntry({
    required this.planned,
    required this.outcome,
    this.file,
  });

  final CentralLogoPreparationItem planned;
  final CentralLogoPrefetchOutcome outcome;
  final File? file;
}

class CentralLogoPrefetchReport {
  CentralLogoPrefetchReport({
    required Iterable<CentralLogoPrefetchEntry> entries,
    required this.reservedAttempts,
    required this.reservedBytes,
  }) : entries = List<CentralLogoPrefetchEntry>.unmodifiable(entries);

  final List<CentralLogoPrefetchEntry> entries;

  // Conservative network reservations; known cooldown/offline outcomes
  // return their quota after the batch. Late cache hits remain charged.
  final int reservedAttempts;
  final int reservedBytes;

  int get downloadedObjects => entries
      .where((entry) => entry.outcome == CentralLogoPrefetchOutcome.downloaded)
      .length;
  int get cachedObjects => entries
      .where((entry) => entry.outcome == CentralLogoPrefetchOutcome.cached)
      .length;
}

class CentralLogoPrefetchExecutor {
  bool _running = false;

  /// Only a previously authenticated CentralLogoPreparationPlan should be
  /// supplied. Tests inject an in-memory fetcher; no default HTTP client is
  /// created here. Production activation requires separate approval.
  ///
  /// Bounded batches; cache hits are verified before checking budget.
  /// Budget reservations are synchronous and precede each network transfer.
  /// Network is impossible unless policy.allowNetwork AND fetch are supplied.
  Future<CentralLogoPrefetchReport> execute({
    required CentralLogoPreparationPlan plan,
    required CentralLogoAssetStore store,
    CentralLogoPrefetchPolicy? policy,
    CentralLogoBytesFetcher? fetch,
  }) async {
    if (_running) {
      throw const CentralCatalogException('Concurrent prefetch execution');
    }
    _running = true;
    try {
      final controls = policy ?? CentralLogoPrefetchPolicy();
      if (controls.allowNetwork && fetch == null) {
        throw const CentralCatalogException(
          'Network prefetch needs an explicitly supplied fetcher',
        );
      }

      // Validate the entire plan before the first possible HTTP request.
      // A malformed duplicate must not cause a partially applied batch.
      final seenDigests = <String>{};
      for (final item in plan.items) {
        if (!seenDigests.add(item.descriptor.sha256)) {
          throw const CentralCatalogException('Duplicate image in prefetch plan');
        }
      }

      final entries = <CentralLogoPrefetchEntry>[];
      var reservedAttempts = 0;
      var reservedBytes = 0;
      final elapsed = Stopwatch()..start();

      // Keep report ordering deterministic and wait for every admitted
      // operation before starting a new batch. Unique digests cannot race
      // each other on the same permanent file.
      for (var offset = 0; offset < plan.items.length;
          offset += controls.maxConcurrent) {
        final batch = plan.items.skip(offset).take(controls.maxConcurrent).toList();
        final cachedFiles = await Future.wait(
          batch.map((item) => store.findVerified(item.descriptor)),
        );
        final pending = <Future<CentralLogoPrefetchEntry>>[];
        for (var i = 0; i < batch.length; i++) {
          final item = batch[i];
          final descriptor = item.descriptor;
          final cached = cachedFiles[i];
          Future<CentralLogoPrefetchEntry> entry(
            CentralLogoPrefetchOutcome outcome, [File? file]
          ) async => CentralLogoPrefetchEntry(
            planned: item, outcome: outcome, file: file,
          );
          if (cached != null) {
            pending.add(entry(CentralLogoPrefetchOutcome.cached, cached));
            continue;
          }
          if (!controls.allowNetwork) {
            pending.add(entry(CentralLogoPrefetchOutcome.offline));
            continue;
          }
          final uri = Uri.tryParse(descriptor.url);
          if (uri == null || !isSafeCentralLogoUrl(uri) ||
              !controls.allowedHosts.contains(uri.host.toLowerCase()) ||
              uri.port != 443) {
            pending.add(entry(CentralLogoPrefetchOutcome.hostBlocked));
            continue;
          }
          if ((controls.maxNetworkDuration != null &&
                  elapsed.elapsed >= controls.maxNetworkDuration!) ||
              reservedAttempts >= controls.maxObjects ||
              descriptor.byteSize > controls.maxBytes - reservedBytes) {
            pending.add(entry(CentralLogoPrefetchOutcome.budgetExceeded));
            continue;
          }

          // No await between the quota check and reservation.
          reservedAttempts++;
          reservedBytes += descriptor.byteSize;
          pending.add(() async {
            final result = await store.ensure(target: descriptor, fetch: fetch);
            if (result.status == CentralLogoCacheStatus.retryDeferred ||
                result.status == CentralLogoCacheStatus.offline) {
              // No transport was attempted. Return the quota for later batches.
              reservedAttempts--;
              reservedBytes -= descriptor.byteSize;
            }
            final outcome = switch (result.status) {
              CentralLogoCacheStatus.cacheHit => CentralLogoPrefetchOutcome.cached,
              CentralLogoCacheStatus.downloaded => CentralLogoPrefetchOutcome.downloaded,
              CentralLogoCacheStatus.retryDeferred => CentralLogoPrefetchOutcome.retryDeferred,
              CentralLogoCacheStatus.downloadRejected => CentralLogoPrefetchOutcome.rejected,
              CentralLogoCacheStatus.offline => CentralLogoPrefetchOutcome.offline,
            };
            return CentralLogoPrefetchEntry(
              planned: item, outcome: outcome, file: result.image,
            );
          }());
        }
        entries.addAll(await Future.wait(pending));
      }
      return CentralLogoPrefetchReport(
        entries: entries,
        reservedAttempts: reservedAttempts,
        reservedBytes: reservedBytes,
      );
    } finally {
      _running = false;
    }
  }
}
