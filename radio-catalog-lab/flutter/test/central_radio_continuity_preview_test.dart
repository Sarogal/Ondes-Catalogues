import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/radio_station_stub.dart';
import 'package:go_radio_flutter_lab/central_legacy_radio_adapter.dart';
import 'package:go_radio_flutter_lab/central_radio_continuity_preview.dart';
import 'package:go_radio_flutter_lab/central_legacy_playback_session.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_projection.dart';

Uint8List _jsonBytes(Object value) =>
    Uint8List.fromList(utf8.encode(jsonEncode(value)));

Map<String, dynamic> _station({
  String goId = 'go-station-000001',
  String status = 'active',
  List<String> aliases = const ['old-primary', 'old-variant'],
  List<String> genres = const ['Heavy'],
}) => <String, dynamic>{
  'go_station_id': goId,
  'display_name': 'Radio fictive',
  'country_code': 'FR',
  'genres': genres,
  'tags': ['heavy metal'],
  'homepage': 'https://example.org/',
  'legacy_aliases': aliases,
  'radio_browser_uuids': [
    for (final alias in aliases)
      {'uuid': alias, 'state': 'historical'}
  ],
  'status': {
    'state': status,
    'reason_code': status == 'active' ? null : 'editorial_suspension',
    'changed_at': '2026-11-15T18:00:00Z',
  },
  'streams': status == 'active'
    ? [
      {
        'stream_id': 'primary',
        'url': 'https://example.org/live.mp3',
        'protocol': 'https',
        'priority': 0,
        'codec': 'mp3',
        'bitrate_kbps': 192,
        'state': 'verified',
      },
      {
        'stream_id': 'secondary',
        'url': 'https://example.org/live.aac',
        'protocol': 'https',
        'priority': 1,
        'codec': 'aac',
        'bitrate_kbps': 96,
        'state': 'verified',
      }
    ]
    : <Map<String, dynamic>>[],
  'logo': null,
  'editorial': {
    'admission_state': 'approved',
    'reviewed_at': '2026-11-15T18:00:00Z',
    'evidence_refs': <String>[],
  },
};

Map<String, dynamic> _catalog(List<Map<String, dynamic>> stations, {
    List<Map<String, dynamic>> tombstones = const [],
  }) => {
  'schema_version': 1,
  'catalog_id': 'grosses-ondes-radio',
  'release_sequence': 1,
  'generated_at': '2026-11-15T18:00:00Z',
  'stations': stations,
  'tombstones': tombstones
};

late SimpleKeyPair _keyPair;
late CentralCatalogVerifier _verifier;

Future<ValidatedCentralCatalog> _valid(List<Map<String, dynamic>> stations, {
  List<Map<String, dynamic>> tombstones = const [],
}) async {
  final catalogBytes = _jsonBytes(_catalog(stations, tombstones: tombstones));
  final digest = crypto.sha256.convert(catalogBytes).toString();
  final pointer = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-15T18:00:00Z',
    'content_sha256': digest,
    'content_length': catalogBytes.length,
    'content_path': 'releases/$digest.json',
    'signature': {
      'algorithm': 'Ed25519',
      'key_id': 'test-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0)),
    }
  };
  final parsed = CentralCatalogPointer.parse(_jsonBytes(pointer));
  final signed = await Ed25519().sign(
      parsed.signatureMessage, keyPair: _keyPair);
  (pointer['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(signed.bytes);
  return _verifier.verify(
      pointerBytes: _jsonBytes(pointer), catalogBytes: catalogBytes);
}

RadioStation _old({required String id, List<String> variants = const []}) =>
    RadioStation(
      id: id,
      name: 'Ancienne radio',
      genre: 'Heavy',
      tags: const ['heavy metal'],
      streamUrl: 'https://example.org/old.mp3',
      logoUrl: '',
      homepage: 'https://example.org',
      countryCode: 'FR',
      codec: 'mp3',
      bitrate: 128,
      votes: 1,
      streamVariants: [
        for (final other in variants)
          RadioStreamVariant(
              stationId: other,
              streamUrl: 'https://example.org/old.mp3',
              codec: 'mp3',
              bitrate: 128)
      ],
    );


void main() {
  setUpAll(() async {
    _keyPair = await Ed25519().newKeyPair();
    final publicKey = await _keyPair.extractPublicKey();
    _verifier = CentralCatalogVerifier(trustedKeys: {'test-only': publicKey});
  });

  test('existing artwork and historical favorite identities survive', () async {
    final verified = await _valid([_station()]);
    final old = _old(id: 'old-primary', variants: ['old-variant']).copyWith(
      logoUrl: 'https://existing.example/radio.png',
      catalogLogoUrl: 'https://other.example/old.png',
      logoSource: 'existing-override',
      votes: 21,
    );
    const adapter = CentralLegacyRadioAdapter();
    final preferred = adapter.preferredMediaIdsFromLegacy(
      catalog: verified, legacyStations: [old]);
    final projected = const CentralCatalogProjector().preview(
      catalog: verified,
      preferredLegacyMediaIds: preferred,
      legacyFavoriteIds: ['old-variant'],
    );
    final preview = const CentralRadioContinuityPlanner().preview(
      catalog: verified, central: projected, legacyStations: [old],
      legacyFavoriteIds: ['old-variant'],
    );
    expect(preview.stations.single.id, 'old-primary');
    expect(preview.stations.single.logoUrl,
        'https://existing.example/radio.png');
    expect(preview.stations.single.catalogLogoUrl,
        'https://other.example/old.png');
    expect(preview.stations.single.logoSource, 'existing-override');
    expect(preview.stations.single.votes, 21);
    expect(preview.stations.single.allStationIds, contains('old-variant'));
    expect(preview.preservedFavoriteIds, ['old-variant']);
    expect(preview.refreshedHistoricalIds, ['old-primary']);
    expect(preview.authorizedForRelease, isFalse);
  });

  test('unmapped RADIO BOB-like legacy entry retains logo and stream', () async {
    final verified = await _valid([_station()]);
    final retained = _old(id: 'bob-death').copyWith(
      name: 'RADIO BOB! DEATH METAL',
      logoUrl: 'https://bob.example/death.png',
    );
    final preview = const CentralRadioContinuityPlanner().preview(
      catalog: verified,
      central: const CentralCatalogProjector().preview(
        catalog: verified, legacyFavoriteIds: []),
      legacyStations: [retained],
      legacyFavoriteIds: ['bob-death'],
    );
    expect(preview.stations.first.id, 'bob-death');
    expect(preview.stations.first.streamUrl, retained.streamUrl);
    expect(preview.stations.first.logoUrl, retained.logoUrl);
    expect(preview.preservedFavoriteIds, ['bob-death']);
    expect(preview.retainedHistoricalIds, ['bob-death']);
  });

  test('two distinct RADIO BOB-like stations never merge due to same name',
      () async {
    final verified = await _valid([_station()]);
    final a = _old(id: 'bob-a').copyWith(
      name: 'RADIO BOB!', logoUrl: 'https://bob.example/a.png');
    final b = _old(id: 'bob-b').copyWith(
      name: 'RADIO BOB!', logoUrl: 'https://bob.example/b.png');
    final plan = const CentralRadioContinuityPlanner().preview(
      catalog: verified,
      central: const CentralCatalogProjector().preview(
        catalog: verified, legacyFavoriteIds: []),
      legacyStations: [a,b],
      legacyFavoriteIds: ['bob-b', 'bob-a'],
    );
    expect(plan.stations.take(2).map((e) => e.id), ['bob-a', 'bob-b']);
    expect(plan.stations.take(2).map((e) => e.logoUrl),
        ['https://bob.example/a.png', 'https://bob.example/b.png']);
    expect(plan.preservedFavoriteIds, ['bob-b', 'bob-a']);
  });

  test('new remote-only station is appended with genre fallback', () async {
    final verified = await _valid([
      _station(goId: 'go-station-000001', aliases: ['old-primary']),
      _station(goId: 'go-station-000002', aliases: ['brand-new']),
    ]);
    final old = _old(id: 'old-primary').copyWith(
      logoUrl: 'https://existing.example/radio.png');
    final ids = const CentralLegacyRadioAdapter()
        .preferredMediaIdsFromLegacy(catalog: verified, legacyStations: [old]);
    final preview = const CentralRadioContinuityPlanner().preview(
      catalog: verified,
      central: const CentralCatalogProjector().preview(
        catalog: verified, legacyFavoriteIds: ['old-primary'],
        preferredLegacyMediaIds: ids),
      legacyStations: [old],
      legacyFavoriteIds: ['old-primary'],
    );
    expect(preview.stations.map((s) => s.id),
        ['old-primary', 'go-station-000002']);
    expect(preview.stations.first.logoUrl,
        'https://existing.example/radio.png');
    expect(preview.stations.last.logoSource, 'genre-fallback');
    expect(preview.appendedCentralGoIds, ['go-station-000002']);
  });

  test('quarantined entry is not allowed to remove old mobile station',
      () async {
    final verified = await _valid([_station(status: 'quarantined')]);
    final old = _old(id: 'old-primary').copyWith(
      logoUrl: 'https://existing.example/radio.png');
    final preview = const CentralRadioContinuityPlanner().preview(
      catalog: verified,
      central: const CentralCatalogProjector().preview(
        catalog: verified, legacyFavoriteIds: ['old-primary']),
      legacyStations: [old],
      legacyFavoriteIds: ['old-primary'],
    );
    expect(preview.stations.single.id, 'old-primary');
    expect(preview.stations.single.streamUrl, old.streamUrl);
    expect(preview.stations.single.logoUrl, old.logoUrl);
    expect(preview.preservedFavoriteIds, ['old-primary']);
  });

  test('central alias collision does not create duplicate cards', () async {
    final verified = await _valid([_station(
      aliases: ['old-primary', 'old-variant'])]);
    final old = _old(id: 'old-primary', variants: ['old-variant']);
    final preview = const CentralRadioContinuityPlanner().preview(
      catalog: verified,
      central: const CentralCatalogProjector().preview(
        catalog: verified, legacyFavoriteIds: []),
      legacyStations: [old], legacyFavoriteIds: [],
    );
    expect(preview.stations, hasLength(1));
    expect(preview.blockedCentralGoIds, ['go-station-000001']);
  });

  test('Android Auto preview keeps legacy logo and favorite artwork',
      () async {
    final verified = await _valid([_station()]);
    final old = _old(id: 'old-primary').copyWith(
      logoUrl: 'https://existing.example/bob-art.png',
      logoSource: 'legacy-override',
    );
    final preferred = const CentralLegacyRadioAdapter()
        .preferredMediaIdsFromLegacy(catalog: verified, legacyStations: [old]);
    final projection = const CentralCatalogProjector().preview(
      catalog: verified, preferredLegacyMediaIds: preferred,
      legacyFavoriteIds: ['old-primary'],
    );
    final playback = CentralLegacyPlaybackSession(
      catalog: verified, preview: projection, legacyStations: [old]);
    final media = playback.resolveAndroidAutoMediaId(
      'go:auto:station:old-primary');
    expect(media.playable, isTrue);
    expect(media.station!.logoUrl, old.logoUrl);
    expect(media.station!.logoSource, old.logoSource);
    expect(playback.activeFavorites(['old-primary']).single.logoUrl,
        old.logoUrl);
  });

  test('duplicate primary IDs fail rather than lose a station', () async {
    final verified = await _valid([_station()]);
    final projected = const CentralCatalogProjector().preview(
      catalog: verified, legacyFavoriteIds: []);
    expect(() => const CentralRadioContinuityPlanner().preview(
      catalog: verified, central: projected,
      legacyStations: [_old(id: 'same'), _old(id: 'same')],
      legacyFavoriteIds: [],
    ), throwsA(isA<CentralCatalogException>()));
  });
}
