// Isolated opt-in bridge: verified offline catalog -> SHA image plan/cache.
// No RootShell/CatalogController import; no startup listener or network client.
// Only loadOffline, prefetchExplicit with default offline policy.
import 'central_logo_asset_store.dart';
import 'central_logo_cache_inspector.dart';
import 'central_logo_prefetch_executor.dart';
import 'central_logo_preparation_plan.dart';
import 'central_radio_catalog_client.dart';
import 'central_radio_catalog_core.dart';

class CentralOfflineLogoState {
  const CentralOfflineLogoState({
    required this.catalog,
    required this.plan,
    required this.inspection,
  });

  /// Only ever sourced from CentralCatalogDiskStore.loadLatest(verifier).
  final ValidatedCentralCatalog catalog;
  final CentralLogoPreparationPlan plan;
  final CentralLogoCacheInspection inspection;
}

class CentralOfflineLogoExecution {
  const CentralOfflineLogoExecution({
    required this.catalog,
    required this.plan,
    required this.report,
  });

  final ValidatedCentralCatalog catalog;
  final CentralLogoPreparationPlan plan;
  final CentralLogoPrefetchReport report;
}

class CentralVerifiedLogoWorkflow {
  CentralVerifiedLogoWorkflow({
    required this.disk,
    required this.verifier,
    required this.store,
    CentralLogoPreparationPlanner? planner,
    CentralLogoCacheInspector? inspector,
    CentralLogoPrefetchExecutor? executor,
  })  : _planner = planner ?? const CentralLogoPreparationPlanner(),
        _inspector = inspector ?? const CentralLogoCacheInspector(),
        _executor = executor ?? CentralLogoPrefetchExecutor();

  final CentralCatalogDiskStore disk;
  final CentralCatalogVerifier verifier;
  final CentralLogoAssetStore store;
  final CentralLogoPreparationPlanner _planner;
  final CentralLogoCacheInspector _inspector;
  final CentralLogoPrefetchExecutor _executor;
  bool _working = false;

  /// Verify the saved Ed25519 pointer, digest and catalog schema every time.
  /// An absent/untrusted snapshot yields null. No file is created or changed.
  Future<CentralOfflineLogoState?> inspectOffline() async {
    return _locked(() async {
      final verified = await disk.loadLatest(verifier);
      if (verified == null) return null;
      final plan = _planner.plan(verified);
      final inspection = await _inspector.inspect(plan: plan, store: store);
      return CentralOfflineLogoState(
        catalog: verified,
        plan: plan,
        inspection: inspection,
      );
    });
  }

  /// Explicit-only operation. Always reload and verify the signed snapshot
  /// instead of trusting a stale plan supplied by UI or raw JSON.
  ///
  /// Default is offline. When a caller explicitly provides a network policy
  /// AND a fetcher, the bounded executor may download. No implicit HTTP.
  Future<CentralOfflineLogoExecution?> prefetchExplicit({
    CentralLogoPrefetchPolicy? policy,
    CentralLogoBytesFetcher? fetch,
  }) async {
    return _locked(() async {
      final verified = await disk.loadLatest(verifier);
      if (verified == null) return null;
      final plan = _planner.plan(verified);
      final report = await _executor.execute(
        plan: plan,
        store: store,
        policy: policy,
        fetch: fetch,
      );
      return CentralOfflineLogoExecution(
        catalog: verified,
        plan: plan,
        report: report,
      );
    });
  }

  Future<T> _locked<T>(Future<T> Function() operation) async {
    if (_working) {
      throw const CentralCatalogException('Concurrent offline logo workflow');
    }
    _working = true;
    try {
      return await operation();
    } finally {
      _working = false;
    }
  }
}
