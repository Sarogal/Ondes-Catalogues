import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_logo_preparation_plan.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

const _shaA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _shaB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

Map<String, dynamic> station(
  String id, {
  String state = 'active',
  String? sha = _shaA,
  int byteSize = 120,
  int width = 512,
  String url = 'https://images.example.org/radio.png',
}) {
  return <String, dynamic>{
    'go_station_id': id,
    'status': <String, dynamic>{'state': state},
    'logo': sha == null
        ? null
        : <String, dynamic>{
            'sha256': sha,
            'asset_id': 'sha256:$sha',
            'byte_size': byteSize,
            'revision': 1,
            'url': url,
            'width': width,
            'height': 512,
            'mime_type': 'image/png',
          },
  };
}

// Synthetic typed snapshot for testing planner behavior only. Real callers
// must obtain this type from CentralCatalogVerifier, not construct it.
ValidatedCentralCatalog fixture(List<Map<String, dynamic>> stations) {
  final pointerBytes = Uint8List.fromList(utf8.encode(jsonEncode({
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-16T12:00:00Z',
    'content_sha256': _shaA,
    'content_length': 2,
    'content_path': 'releases/$_shaA.json',
    'signature': {
      'algorithm': 'Ed25519',
      'key_id': 'test-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0)),
    },
  })));
  return ValidatedCentralCatalog(
    CentralCatalogPointer.parse(pointerBytes),
    pointerBytes,
    Uint8List.fromList(utf8.encode('{}')),
    stations,
    const <String, String>{},
    stations.map((s) => s['go_station_id'] as String).toSet(),
    stations.where((s) => s['status']['state'] == 'active')
        .map((s) => s['go_station_id'] as String).toSet(),
  );
}

void main() {
  const planner = CentralLogoPreparationPlanner();

  test('shared SHA creates one plan item, never one request per radio', () {
    final result = planner.plan(fixture([
      station('go-station-000002'),
      station('go-station-000001'),
      station('go-station-000003', state: 'quarantined', sha: _shaB),
      station('go-station-000004', sha: null),
      station('go-station-000005', state: 'retired'),
    ]));
    expect(result.uniqueImageCount, 1);
    expect(result.representedStationCount, 2);
    expect(result.maximumUncachedBytes, 120);
    expect(result.items.single.descriptor.sha256, _shaA);
    expect(result.items.single.stationIds,
        ['go-station-000001', 'go-station-000002']);
    expect(result.activeWithoutLogo, ['go-station-000004']);
    expect(result.excludedInactive,
        ['go-station-000003', 'go-station-000005']);
  });

  test('deterministic digest order and independent objects', () {
    final result = planner.plan(fixture([
      station('go-station-000009', sha: _shaB, byteSize: 200),
      station('go-station-000001', sha: _shaA, byteSize: 120),
    ]));
    expect(result.items.map((item) => item.descriptor.sha256).toList(),
        [_shaA, _shaB]);
    expect(result.maximumUncachedBytes, 320);
  });

  test('rejects a signed image URL pointing to loopback', () {
    expect(
      () => planner.plan(fixture([
        station('go-station-000001', url: 'https://127.0.0.1/logo.png'),
      ])),
      throwsA(isA<CentralCatalogException>()),
    );
  });

  test('rejects metadata conflict for one image SHA', () {
    expect(
      () => planner.plan(fixture([
        station('go-station-000001', width: 512),
        station('go-station-000002', width: 1024),
      ])),
      throwsA(isA<CentralCatalogException>()),
    );
  });

  test('plan collections are immutable and cannot alter the snapshot', () {
    final catalog = fixture([station('go-station-000001')]);
    final result = planner.plan(catalog);
    expect(() => result.items.add(result.items.single), throwsUnsupportedError);
    expect(() => result.items.single.stationIds.add('fake'),
        throwsUnsupportedError);
    expect(catalog.stations, hasLength(1));
  });

  test('no logo means no image work even for active station', () {
    final result = planner.plan(
      fixture([station('go-station-000010', sha: null)]),
    );
    expect(result.uniqueImageCount, 0);
    expect(result.activeWithoutLogo, ['go-station-000010']);
  });
}
