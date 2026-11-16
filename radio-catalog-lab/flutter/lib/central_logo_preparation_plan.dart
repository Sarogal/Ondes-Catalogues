// Isolated, read-only logo plan produced only from an authenticated snapshot.
// No network, cache writes, favorites, UI or Android Auto side effects.
// A separate, explicitly authorized step must execute any downloads.
import 'central_logo_asset_store.dart';
import 'central_logo_http_fetcher.dart';
import 'central_radio_catalog_core.dart';

class CentralLogoPreparationItem {
  CentralLogoPreparationItem({
    required this.descriptor,
    required Iterable<String> stationIds,
  }) : stationIds = List<String>.unmodifiable(stationIds);

  final CentralLogoDescriptor descriptor;

  /// Multiple stations may use one immutable SHA-256 image object.
  final List<String> stationIds;
}

class CentralLogoPreparationPlan {
  CentralLogoPreparationPlan({
    required Iterable<CentralLogoPreparationItem> items,
    required Iterable<String> activeWithoutLogo,
    required Iterable<String> excludedInactive,
  }) : items = List<CentralLogoPreparationItem>.unmodifiable(items),
       activeWithoutLogo = List<String>.unmodifiable(activeWithoutLogo),
       excludedInactive = List<String>.unmodifiable(excludedInactive);

  /// One possible object fetch per distinct digest; never per station.
  final List<CentralLogoPreparationItem> items;
  final List<String> activeWithoutLogo;
  final List<String> excludedInactive;

  int get uniqueImageCount => items.length;
  int get representedStationCount =>
      items.fold<int>(0, (count, item) => count + item.stationIds.length);

  /// Upper bound before cache hits or reuse of verified legacy objects.
  int get maximumUncachedBytes =>
      items.fold<int>(0, (count, item) => count + item.descriptor.byteSize);
}

class CentralLogoPreparationPlanner {
  const CentralLogoPreparationPlanner();

  /// [catalog] MUST come from CentralCatalogVerifier.verify or the verified
  /// offline snapshot reader, not from an unchecked JSON map.
  ///
  /// This only describes work; it never calls CentralLogoAssetStore.ensure,
  /// transfers image bytes or replaces the legacy logo synchronizer.
  CentralLogoPreparationPlan plan(ValidatedCentralCatalog catalog) {
    final grouped = <String, _PendingLogo>{};
    final activeWithoutLogo = <String>[];
    final excludedInactive = <String>[];

    for (final station in catalog.stations) {
      final id = station['go_station_id'] as String;
      final status = (station['status'] as Map<String, dynamic>)['state'];
      if (status != 'active') {
        excludedInactive.add(id);
        continue;
      }

      final logo = CentralLogoDescriptor.fromSignedStation(station);
      if (logo == null) {
        activeWithoutLogo.add(id);
        continue;
      }
      // Require a publicly routable HTTPS host at this boundary, even if an
      // earlier producer accepted a less restrictive logo URL.
      if (!isSafeCentralLogoUrl(Uri.parse(logo.url))) {
        throw const CentralCatalogException(
          'Unsafe central logo URL in authenticated snapshot',
        );
      }

      final prior = grouped[logo.sha256];
      if (prior == null) {
        grouped[logo.sha256] = _PendingLogo(logo, [id]);
      } else {
        // A signed catalog already enforces this, but fail closed if a future
        // caller constructs an inconsistent snapshot in memory.
        final first = prior.descriptor;
        if (first.byteSize != logo.byteSize ||
            first.width != logo.width ||
            first.height != logo.height ||
            first.mimeType != logo.mimeType) {
          throw const CentralCatalogException(
            'One logo SHA has conflicting image metadata',
          );
        }
        prior.stationIds.add(id);
      }
    }

    final digests = grouped.keys.toList()..sort();
    return CentralLogoPreparationPlan(
      items: [
        for (final sha in digests)
          CentralLogoPreparationItem(
            descriptor: grouped[sha]!.descriptor,
            stationIds: grouped[sha]!.stationIds..sort(),
          ),
      ],
      activeWithoutLogo: activeWithoutLogo..sort(),
      excludedInactive: excludedInactive..sort(),
    );
  }
}

class _PendingLogo {
  _PendingLogo(this.descriptor, this.stationIds);
  final CentralLogoDescriptor descriptor;
  final List<String> stationIds;
}
