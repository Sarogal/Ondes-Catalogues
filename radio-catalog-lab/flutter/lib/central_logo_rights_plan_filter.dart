// Pure, DEFAULT-DENY logo plan filter for a future authorized catalog rollout.
//
// IMPORTANT: A signed SHA verifies image integrity, not permission to rehost.
// approvedDigestByStation must ONLY come from a separately reviewed rights
// registry and a signed publisher manifest. The v1 rights registry supplies
// ZERO permissions and cannot enable any source. This class has no I/O,
// network, Android integration or production wiring.
import 'central_logo_preparation_plan.dart';
import 'central_radio_catalog_core.dart';

class CentralLogoRightsFilteredPlan {
  CentralLogoRightsFilteredPlan({
    required this.plan,
    required Iterable<String> deniedRightsStationIds,
  }) : deniedRightsStationIds =
           List<String>.unmodifiable(deniedRightsStationIds);

  final CentralLogoPreparationPlan plan;
  final List<String> deniedRightsStationIds;

  int get blockedByRightsCount => deniedRightsStationIds.length;
}

class CentralLogoRightsPlanFilter {
  const CentralLogoRightsPlanFilter();

  /// An empty allowlist (as required by the initial v1 rights audit) removes
  /// ALL central artwork from the prefetch plan. It preserves the existing
  /// legacy image / bundled genre fallbacks; those are not modified here.
  ///
  /// The supplied approvals are station-ID PLUS EXACT SHA, not merely a
  /// domain, logo filename or radio genre. This forbids an approval for one
  /// channel to implicitly authorize another or a changed logo revision.
  CentralLogoRightsFilteredPlan restrict({
    required CentralLogoPreparationPlan original,
    Map<String, String> approvedDigestByStation = const <String, String>{},
  }) {
    final seen = <String>{};
    final allowedIds = <String>{};
    final blockedIds = <String>{};
    final retained = <CentralLogoPreparationItem>[];

    final allNonActiveIds = <String>{
      ...original.activeWithoutLogo,
      ...original.excludedInactive,
    };
    if (original.activeWithoutLogo.toSet().length !=
            original.activeWithoutLogo.length ||
        original.excludedInactive.toSet().length !=
            original.excludedInactive.length ||
        original.activeWithoutLogo.toSet().intersection(
          original.excludedInactive.toSet(),
        ).isNotEmpty) {
      throw const CentralCatalogException('Conflicting original logo plan IDs');
    }

    for (final item in original.items) {
      final allowedForImage = <String>[];
      for (final id in item.stationIds) {
        if (id.isEmpty || !seen.add(id) || allNonActiveIds.contains(id)) {
          throw const CentralCatalogException(
            'Duplicate or inactive station in logo plan',
          );
        }
        if (!approvedDigestByStation.containsKey(id)) {
          blockedIds.add(id);
          continue;
        }
        if (approvedDigestByStation[id] != item.descriptor.sha256) {
          throw const CentralCatalogException(
            'Rights permit digest mismatch: refuse image revision',
          );
        }
        allowedIds.add(id);
        allowedForImage.add(id);
      }
      if (allowedForImage.isNotEmpty) {
        allowedForImage.sort();
        retained.add(
          CentralLogoPreparationItem(
            descriptor: item.descriptor,
            stationIds: allowedForImage,
          ),
        );
      }
    }

    if (!seen.containsAll(approvedDigestByStation.keys) ||
        approvedDigestByStation.length != allowedIds.length) {
      throw const CentralCatalogException(
        'Rights allowlist refers to a missing or inactive station',
      );
    }

    final withoutLogo = <String>{
      ...original.activeWithoutLogo,
      ...blockedIds,
    }.toList()..sort();
    final denied = blockedIds.toList()..sort();

    return CentralLogoRightsFilteredPlan(
      plan: CentralLogoPreparationPlan(
        items: retained,
        activeWithoutLogo: withoutLogo,
        excludedInactive: original.excludedInactive,
      ),
      deniedRightsStationIds: denied,
    );
  }
}
