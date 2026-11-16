// Explicit, read-only inspection of SHA-addressed logo objects.
// Not connected to RootShell, Android Auto or the legacy logo synchronizer.
// Does not download, adopt, delete, rename, create or repair image files.
import 'dart:io';

import 'central_logo_asset_store.dart';
import 'central_logo_preparation_plan.dart';

class CentralLogoInspectedAsset {
  CentralLogoInspectedAsset({
    required this.planned,
    required this.verifiedFile,
  });

  final CentralLogoPreparationItem planned;
  final File? verifiedFile;

  bool get isCached => verifiedFile != null;
}

class CentralLogoCacheInspection {
  CentralLogoCacheInspection(Iterable<CentralLogoInspectedAsset> assets)
      : assets = List<CentralLogoInspectedAsset>.unmodifiable(assets);

  final List<CentralLogoInspectedAsset> assets;

  int get cachedObjects =>
      assets.where((asset) => asset.isCached).length;

  int get missingObjects =>
      assets.where((asset) => !asset.isCached).length;

  /// Upper bound of verified bytes still absent on disk; no fetch occurs.
  int get missingBytes => assets
      .where((asset) => !asset.isCached)
      .fold<int>(
        0,
        (total, asset) => total + asset.planned.descriptor.byteSize,
      );

  int get cachedStationEntries => assets
      .where((asset) => asset.isCached)
      .fold<int>(
        0,
        (total, asset) => total + asset.planned.stationIds.length,
      );
}

class CentralLogoCacheInspector {
  const CentralLogoCacheInspector();

  /// The plan must originate from a trusted signed catalog.
  /// Revalidation happens through the injected real image decoder.
  /// A broken object is reported missing, never removed or overwritten.
  Future<CentralLogoCacheInspection> inspect({
    required CentralLogoPreparationPlan plan,
    required CentralLogoAssetStore store,
  }) async {
    final entries = <CentralLogoInspectedAsset>[];
    for (final planned in plan.items) {
      final verified = await store.findVerified(planned.descriptor);
      entries.add(
        CentralLogoInspectedAsset(
          planned: planned,
          verifiedFile: verified,
        ),
      );
    }
    return CentralLogoCacheInspection(entries);
  }
}
