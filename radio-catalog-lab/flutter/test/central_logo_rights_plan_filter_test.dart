import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_logo_preparation_plan.dart';
import 'package:go_radio_flutter_lab/central_logo_rights_plan_filter.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

const shaA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const shaB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

CentralLogoDescriptor descriptor(String digest) => CentralLogoDescriptor(
      sha256: digest,
      byteSize: 180,
      revision: 1,
      url: 'https://images.example.org/$digest.png',
      width: 256,
      height: 256,
      mimeType: 'image/png',
    );

CentralLogoPreparationPlan fixture() => CentralLogoPreparationPlan(
      items: <CentralLogoPreparationItem>[
        CentralLogoPreparationItem(
          descriptor: descriptor(shaA),
          stationIds: const <String>['station-A1', 'station-A2'],
        ),
        CentralLogoPreparationItem(
          descriptor: descriptor(shaB),
          stationIds: const <String>['station-B1'],
        ),
      ],
      activeWithoutLogo: const <String>['station-no-logo'],
      excludedInactive: const <String>['station-quarantined'],
    );

void main() {
  const filter = CentralLogoRightsPlanFilter();

  test('DEFAULT DENY: no rights means no central SHA may be fetched', () {
    final result = filter.restrict(original: fixture());
    expect(result.plan.items, isEmpty);
    expect(result.plan.uniqueImageCount, 0);
    expect(result.plan.maximumUncachedBytes, 0);
    expect(result.blockedByRightsCount, 3);
    expect(result.deniedRightsStationIds,
        <String>['station-A1', 'station-A2', 'station-B1']);
    expect(result.plan.activeWithoutLogo, <String>[
      'station-A1', 'station-A2', 'station-B1', 'station-no-logo',
    ]);
    expect(result.plan.excludedInactive, ['station-quarantined']);
  });

  test('permission for one variant never authorizes a sibling with same SHA',
      () {
    final result = filter.restrict(
      original: fixture(),
      approvedDigestByStation: const <String, String>{'station-A1': shaA},
    );
    expect(result.plan.items, hasLength(1));
    expect(result.plan.items.single.stationIds, ['station-A1']);
    expect(result.plan.items.single.descriptor.sha256, shaA);
    expect(result.deniedRightsStationIds, ['station-A2', 'station-B1']);
    expect(result.plan.maximumUncachedBytes, 180);
  });

  test('exact per-ID grants allow shared SHA once, not per radio', () {
    final result = filter.restrict(
      original: fixture(),
      approvedDigestByStation: const <String, String>{
        'station-A1': shaA,
        'station-A2': shaA,
        'station-B1': shaB,
      },
    );
    expect(result.plan.uniqueImageCount, 2);
    expect(result.plan.representedStationCount, 3);
    expect(result.plan.maximumUncachedBytes, 360);
    expect(result.deniedRightsStationIds, isEmpty);
  });

  test('wrong SHA is rejected even if station ID is recognized', () {
    expect(() => filter.restrict(
          original: fixture(),
          approvedDigestByStation: const <String, String>{'station-A1': shaB},
        ), throwsA(isA<CentralCatalogException>()));
  });

  test('authorization cannot carry forward to changed logo SHA', () {
    final altered = CentralLogoPreparationPlan(
      items: <CentralLogoPreparationItem>[
        CentralLogoPreparationItem(
          descriptor: descriptor(shaB),
          stationIds: const <String>['station-A1'],
        ),
      ],
      activeWithoutLogo: const <String>[],
      excludedInactive: const <String>[],
    );
    expect(() => filter.restrict(
          original: altered,
          approvedDigestByStation: const <String, String>{'station-A1': shaA},
        ), throwsA(isA<CentralCatalogException>()));
  });

  test('unknown station and removed station cannot be authorized', () {
    for (final id in ['station-unknown', 'station-no-logo',
                       'station-quarantined']) {
      expect(() => filter.restrict(
            original: fixture(),
            approvedDigestByStation: <String, String>{id: shaA},
          ), throwsA(isA<CentralCatalogException>()));
    }
  });

  test('duplicate station ID in different image objects is rejected', () {
    final original = CentralLogoPreparationPlan(
      items: <CentralLogoPreparationItem>[
        CentralLogoPreparationItem(
          descriptor: descriptor(shaA),
          stationIds: const <String>['station-duplicate'],
        ),
        CentralLogoPreparationItem(
          descriptor: descriptor(shaB),
          stationIds: const <String>['station-duplicate'],
        ),
      ],
      activeWithoutLogo: const <String>[],
      excludedInactive: const <String>[],
    );
    expect(() => filter.restrict(original: original),
        throwsA(isA<CentralCatalogException>()));
  });

  test('inactive and active-without-logo ID collision is rejected', () {
    final original = CentralLogoPreparationPlan(
      items: const <CentralLogoPreparationItem>[],
      activeWithoutLogo: const <String>['both'],
      excludedInactive: const <String>['both'],
    );
    expect(() => filter.restrict(original: original),
        throwsA(isA<CentralCatalogException>()));
  });

  test('non-active ID attached to an image is rejected', () {
    final original = CentralLogoPreparationPlan(
      items: <CentralLogoPreparationItem>[
        CentralLogoPreparationItem(
          descriptor: descriptor(shaA),
          stationIds: const <String>['retired'],
        ),
      ],
      activeWithoutLogo: const <String>[],
      excludedInactive: const <String>['retired'],
    );
    expect(() => filter.restrict(original: original),
        throwsA(isA<CentralCatalogException>()));
  });

  test('empty station identifier in an image plan is rejected', () {
    final original = CentralLogoPreparationPlan(
      items: <CentralLogoPreparationItem>[
        CentralLogoPreparationItem(
          descriptor: descriptor(shaA),
          stationIds: const <String>[''],
        ),
      ],
      activeWithoutLogo: const <String>[],
      excludedInactive: const <String>[],
    );
    expect(() => filter.restrict(original: original),
        throwsA(isA<CentralCatalogException>()));
  });

  test('original signed plan remains unchanged, allowing fallback or rollback',
      () {
    final original = fixture();
    final result = filter.restrict(original: original);
    expect(original.uniqueImageCount, 2);
    expect(original.representedStationCount, 3);
    expect(original.activeWithoutLogo, ['station-no-logo']);
    expect(result.plan.items, isEmpty);
  });

  test('denied stations and no-logo stations sorted deterministically', () {
    final original = CentralLogoPreparationPlan(
      items: <CentralLogoPreparationItem>[
        CentralLogoPreparationItem(
          descriptor: descriptor(shaA),
          stationIds: const <String>['z', 'a', 'm'],
        ),
      ],
      activeWithoutLogo: const <String>['v'],
      excludedInactive: const <String>[],
    );
    final result = filter.restrict(original: original);
    expect(result.deniedRightsStationIds, ['a', 'm', 'z']);
    expect(result.plan.activeWithoutLogo, ['a', 'm', 'v', 'z']);
  });
}
