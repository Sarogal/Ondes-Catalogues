// Pure-Dart, read-only preflight for comparing a supplied V64 station snapshot
// against the central catalog. It cannot authorize release or mutate favorites.
import 'central_radio_catalog_core.dart';

class CentralLegacyObservation {
  CentralLegacyObservation({
    required this.primaryMediaId,
    required Iterable<String> historicalIds,
  }) : historicalIds = Set<String>.unmodifiable(historicalIds);

  final String primaryMediaId;
  final Set<String> historicalIds;
}

class CentralLegacyCoverageReport {
  const CentralLegacyCoverageReport({
    required this.sourceLabel,
    required this.observedLegacyStations,
    required this.mappedLegacyStations,
    required this.missingPrimaryMediaIds,
    required this.ambiguousPrimaryMediaIds,
    required this.unmappedHistoricalIds,
    required this.duplicatePrimaryMediaIds,
    required this.unresolvedFavoriteIds,
    required this.matchesObservedBaseline,
  });

  final String sourceLabel;
  final int observedLegacyStations;
  final int mappedLegacyStations;
  final List<String> missingPrimaryMediaIds;
  final List<String> ambiguousPrimaryMediaIds;
  final List<String> unmappedHistoricalIds;
  final List<String> duplicatePrimaryMediaIds;
  final List<String> unresolvedFavoriteIds;

  /// Only compares the explicit observations provided by the caller.
  /// Never a claim about an APK/device that has not been inspected.
  final bool matchesObservedBaseline;

  /// More gates are required: editorial review, real streams, Android Auto,
  /// device favorites and logo cache. This prototype cannot authorize go-live.
  bool get readyForRelease => false;
}

class CentralCatalogMigrationGate {
  const CentralCatalogMigrationGate();

  CentralLegacyCoverageReport audit({
    required ValidatedCentralCatalog catalog,
    required Iterable<CentralLegacyObservation> legacyStations,
    required Iterable<String> legacyFavoriteIds,
    required String sourceLabel,
  }) {
    if (sourceLabel.trim().isEmpty) {
      throw const CentralCatalogException('Missing legacy baseline provenance');
    }

    final observations = List<CentralLegacyObservation>.unmodifiable(legacyStations);
    final seenPrimary = <String>{};
    final missing = <String>{};
    final ambiguous = <String>{};
    final unmapped = <String>{};
    final duplicate = <String>{};
    var mapped = 0;

    String? ownerOf(String value) =>
        catalog.aliasOwners[value] ??
        (catalog.goIds.contains(value) ? value : null);

    for (final item in observations) {
      final primary = item.primaryMediaId;
      if (primary.trim().isEmpty || !item.historicalIds.contains(primary)) {
        throw const CentralCatalogException('Invalid legacy station observation');
      }
      if (!seenPrimary.add(primary)) {
        duplicate.add(primary);
        continue;
      }
      final owner = ownerOf(primary);
      if (owner == null) {
        missing.add(primary);
      } else {
        mapped++;
      }
      final owners = <String>{};
      for (final id in item.historicalIds) {
        if (id.trim().isEmpty) {
          throw const CentralCatalogException('Empty historical UUID');
        }
        final resolved = ownerOf(id);
        if (resolved == null) {
          unmapped.add(id);
        } else {
          owners.add(resolved);
        }
      }
      if (owners.length > 1 || (owner != null && !owners.contains(owner))) {
        ambiguous.add(primary);
      }
    }

    final unresolvedFavorites = <String>{};
    for (final id in legacyFavoriteIds) {
      if (ownerOf(id) == null) unresolvedFavorites.add(id);
    }

    final matched = observations.isNotEmpty &&
        missing.isEmpty && ambiguous.isEmpty && unmapped.isEmpty &&
        duplicate.isEmpty && unresolvedFavorites.isEmpty &&
        mapped == observations.length;

    return CentralLegacyCoverageReport(
      sourceLabel: sourceLabel,
      observedLegacyStations: observations.length,
      mappedLegacyStations: mapped,
      missingPrimaryMediaIds:
          List<String>.unmodifiable(missing.toList()..sort()),
      ambiguousPrimaryMediaIds:
          List<String>.unmodifiable(ambiguous.toList()..sort()),
      unmappedHistoricalIds:
          List<String>.unmodifiable(unmapped.toList()..sort()),
      duplicatePrimaryMediaIds:
          List<String>.unmodifiable(duplicate.toList()..sort()),
      unresolvedFavoriteIds:
          List<String>.unmodifiable(unresolvedFavorites.toList()..sort()),
      matchesObservedBaseline: matched,
    );
  }
}
