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
  }) : allowedHosts = Set<String>.unmodifiable(
          allowedHosts.map((host) => host.toLowerCase()),
        ) {
    if (maxObjects < 0 || maxBytes < 0) {
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

  // Conservative maximum reservations, not a measure of HTTP traffic.
  // Store-level persistent cooldown can suppress a reserved request.
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
  /// One object at a time. Cache hits are verified before checking budget.
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

      for (final item in plan.items) {
        final descriptor = item.descriptor;
        final cached = await store.findVerified(descriptor);
        if (cached != null) {
          entries.add(CentralLogoPrefetchEntry(
            planned: item,
            outcome: CentralLogoPrefetchOutcome.cached,
            file: cached,
          ));
          continue;
        }
        if (!controls.allowNetwork) {
          entries.add(CentralLogoPrefetchEntry(
            planned: item,
            outcome: CentralLogoPrefetchOutcome.offline,
          ));
          continue;
        }
        final uri = Uri.tryParse(descriptor.url);
        if (uri == null ||
            !isSafeCentralLogoUrl(uri) ||
            !controls.allowedHosts.contains(uri.host.toLowerCase()) ||
            uri.port != 443) {
          entries.add(CentralLogoPrefetchEntry(
            planned: item,
            outcome: CentralLogoPrefetchOutcome.hostBlocked,
          ));
          continue;
        }
        if (reservedAttempts >= controls.maxObjects ||
            descriptor.byteSize > controls.maxBytes - reservedBytes) {
          entries.add(CentralLogoPrefetchEntry(
            planned: item,
            outcome: CentralLogoPrefetchOutcome.budgetExceeded,
          ));
          continue;
        }

        // Reserve before any awaited network operation.
        reservedAttempts++;
        reservedBytes += descriptor.byteSize;
        final result = await store.ensure(target: descriptor, fetch: fetch);
        final outcome = switch (result.status) {
          CentralLogoCacheStatus.cacheHit =>
            CentralLogoPrefetchOutcome.cached,
          CentralLogoCacheStatus.downloaded =>
            CentralLogoPrefetchOutcome.downloaded,
          CentralLogoCacheStatus.retryDeferred =>
            CentralLogoPrefetchOutcome.retryDeferred,
          CentralLogoCacheStatus.downloadRejected =>
            CentralLogoPrefetchOutcome.rejected,
          CentralLogoCacheStatus.offline =>
            CentralLogoPrefetchOutcome.offline,
        };
        entries.add(CentralLogoPrefetchEntry(
          planned: item,
          outcome: outcome,
          file: result.image,
        ));
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
