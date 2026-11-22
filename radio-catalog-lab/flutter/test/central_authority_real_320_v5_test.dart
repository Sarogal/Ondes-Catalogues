import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_authoritative_catalog_selector.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_client.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

/// Exactly the 320-identity unsigned v5 artifact independently assembled
/// from the shipped V64 radios, 358 audio probes and historical SHA images.
/// NO production or TEST signing key is ever accessed here.
final fixture = File(const String.fromEnvironment('GO_REAL_V5_FIXTURE',
    defaultValue: 'test/fixtures/full_v5_unsigned.json'));

Uint8List encodeJson(Object value) =>
    Uint8List.fromList(utf8.encode(jsonEncode(value)));

Future<ValidatedCentralCatalog> syntheticSignature(
  Map<String, dynamic> catalog,
  KeyPair key,
  CentralCatalogVerifier verifier, {
  ValidatedCentralCatalog? previous,
}) async {
  final data = encodeJson(catalog);
  final digest = crypto.sha256.convert(data).toString();
  final sequence = catalog['release_sequence'] as int;
  final pointer = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': sequence,
    'published_at': '2026-11-22T21:20:00Z',
    'content_sha256': digest,
    'content_length': data.length,
    'content_path': 'releases/$digest.json',
    'signature': <String, dynamic>{
      'algorithm': 'Ed25519',
      'key_id': 'test-full-v5-ephemeral-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0)),
    }
  };
  final parsed = CentralCatalogPointer.parse(encodeJson(pointer));
  final sig = await Ed25519().sign(parsed.signatureMessage, keyPair: key);
  (pointer['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(sig.bytes);
  return verifier.verify(
    pointerBytes: encodeJson(pointer), catalogBytes: data, previous: previous);
}

CentralRadioCatalogClient testedClient(
    Directory directory, CentralCatalogVerifier verifier,
    ValidatedCentralCatalog Function() latest, {
    bool networkError = false,
    }) {
  return CentralRadioCatalogClient(
    baseUri: Uri.parse('https://fixture.example.org/central/'),
    verifier: verifier,
    disk: CentralCatalogDiskStore(directory),
    fetch: (uri, limit) async {
      if (networkError) throw const SocketException('Offline simulator');
      final snapshot = latest();
      final bytes = uri.path.endsWith('current.json')
          ? snapshot.pointerBytes
          : snapshot.catalogBytes;
      if (bytes.length > limit) {
        throw const CentralCatalogException('Synthetic payload exceeds limit');
      }
      return bytes;
    },
  );
}

void main() {
  late Map<String, dynamic> authenticDraft;
  late KeyPair temporaryKey;
  late CentralCatalogVerifier verifier;
  late Directory tempFolder;
  setUpAll(() async {
    if (!fixture.existsSync()) return;
    final json = jsonDecode(await fixture.readAsString());
    if (json is! Map<String, dynamic>) {
      throw StateError('Full v5 fixture must be a JSON object');
    }
    authenticDraft = json;
    temporaryKey = await Ed25519().newKeyPair();
    verifier = CentralCatalogVerifier(trustedKeys: {
      'test-full-v5-ephemeral-only': (await temporaryKey.extractPublicKey()) as SimplePublicKey,
    });
  });

  setUp(() async {
    tempFolder = await Directory.systemTemp.createTemp('go-full-v5-authority-');
  });
  tearDown(() async {
    await tempFolder.delete(recursive: true);
  });

  test('real 320-station v5 passes signed Dart verifier, signed-only Flutter projection and offline startup',
      () async {
    final verified = await syntheticSignature(
        authenticDraft, temporaryKey, verifier);
    expect(verified.stations, hasLength(320));
    expect(verified.activeIds, hasLength(309));

    final oldHardUuid = '9609c009-0601-11e8-ae97-52543be04c81';
    final otherHardUuid = '960b1fda-0601-11e8-ae97-52543be04c81';
    final oldFav = <String>[oldHardUuid, otherHardUuid,
        'go-station-000015', 'unknown-historical-favorite'];

    final remote = testedClient(tempFolder, verifier, () => verified);
    const selector = CentralAuthoritativeCatalogSelector();
    final first = await selector.select(client: remote,
        favoriteIds: oldFav, allowNetwork: true);
    expect(first, isNotNull,
        reason: 'Signed historical v5 may not be discarded as unsupported');
    expect(first!.source, CentralAuthoritySource.signedNetwork);
    expect(first.stations, hasLength(309));
    final signedArtworkRows = verified.stations.where(
      (s) => (s['status'] as Map<String, dynamic>)['state'] == 'active'
          && s['logo'] is Map<String, dynamic>,
    ).toList();
    expect(signedArtworkRows.length, greaterThanOrEqualTo(80));
    final knownUrlByOwner = <String, String>{
      for (final record in signedArtworkRows)
        record['go_station_id'] as String:
            (record['logo'] as Map<String, dynamic>)['url'] as String,
    };
    final actualLogoRows = first.stations.where((s) =>
        s.logoSource == 'central-signed-sha-only').toList();
    expect(actualLogoRows, hasLength(signedArtworkRows.length));
    for (final imageStation in actualLogoRows) {
      final goId = verified.aliasOwners[imageStation.id] ?? imageStation.id;
      expect(imageStation.logoUrl, knownUrlByOwner[goId]);
      expect(imageStation.catalogLogoUrl, knownUrlByOwner[goId]);
    }
    expect(first.stations.map((s) => s.id).toSet(), hasLength(309));
    final hard = first.stations.where((s) => s.name == 'HardRadio').single;
    expect(hard.id, oldHardUuid);
    expect(hard.allStationIds, contains(otherHardUuid));
    expect(hard.streamVariants.map((v) => v.streamUrl).toSet(),
        contains('http://3634.cloudrad.io/stream/3//hardradio4.aac'));
    expect(first.unavailableFavoriteIds, contains('go-station-000015'));
    expect(first.unresolvedFavoriteIds, contains('unknown-historical-favorite'));
    expect(first.originalFavoriteIds, oldFav);

    // Every primary ID is determined by signed data, not legacy bootstrap.
    final signedActive = verified.stations.where((s) =>
      (s['status'] as Map<String, dynamic>)['state'] == 'active');
    final idsFromSignature = <String>{
      for (final row in signedActive)
        if ((row['legacy_aliases'] as List).isNotEmpty)
          (row['legacy_aliases'] as List).first as String
        else row['go_station_id'] as String
    };
    expect(idsFromSignature, first.stations.map((s) => s.id).toSet());

    // After network goes away, only last authenticated snapshot is used.
    final offline = await selector.select(
        client: testedClient(tempFolder, verifier, () => verified,
            networkError: true),
        favoriteIds: oldFav);
    expect(offline, isNotNull);
    expect(offline!.source, CentralAuthoritySource.signedDisk);
    expect(offline.stations, hasLength(309));
    expect(offline.stations.map((s) => s.id).toList(),
           first.stations.map((s) => s.id).toList());
    expect(first.productionReleaseAuthorized, isFalse);
  }, skip: !fixture.existsSync());

  test('server-only v6 changes a stream, replaces logo SHA and adds new station, same client and offline disk',
      () async {
    final v5 = await syntheticSignature(authenticDraft, temporaryKey, verifier);
    var current = v5;
    final remote = testedClient(tempFolder, verifier, () => current);
    const selector = CentralAuthoritativeCatalogSelector();
    final previous = await selector.select(client: remote,
        favoriteIds: [], allowNetwork: true);
    expect(previous!.stations, hasLength(309));

    final next = jsonDecode(jsonEncode(authenticDraft)) as Map<String, dynamic>;
    next['release_sequence'] = 6;
    next['generated_at'] = '2026-11-22T21:30:00Z';
    final stations = (next['stations'] as List).cast<Map<String, dynamic>>();
    final hard = stations.singleWhere((s) => s['display_name'] == 'HardRadio');
    final streams = (hard['streams'] as List).cast<Map<String, dynamic>>();
    final firstStream = streams.first;
    firstStream['url'] = 'https://new-radio-stream.example.org/hardradio.mp3';
    firstStream['protocol'] = 'https';
    firstStream['state'] = 'verified';

    final withLogo = stations.firstWhere((s) => s['logo'] is Map);
    final logo = withLogo['logo'] as Map<String, dynamic>;
    final replacementSha = List<String>.filled(64, 'c').join();
    logo['sha256'] = replacementSha;
    logo['asset_id'] = 'sha256:' + replacementSha;
    logo['url'] = 'https://cdn.example.org/new-verified-logo.png';
    logo['revision'] = (logo['revision'] as int) + 1;

    // A totally new provider need not exist in the built-in app.
    final newcomer = jsonDecode(jsonEncode(hard)) as Map<String, dynamic>;
    newcomer['go_station_id'] = 'go-station-901000';
    newcomer['display_name'] = 'New server-only Heavy Metal Station';
    newcomer['legacy_aliases'] = <String>[];
    newcomer['radio_browser_uuids'] = <Map<String, dynamic>>[];
    newcomer['streams'] = [<String, dynamic>{
      'stream_id': 'new-stream',
      'url': 'https://new-provider.example.org/radio',
      'protocol': 'https', 'priority': 0,
      'codec': 'MP3', 'bitrate_kbps': 192, 'state': 'verified',
    }];
    newcomer['logo'] = null;
    newcomer['editorial'] = <String, dynamic>{
      'admission_state': 'approved',
      'reviewed_at': '2026-11-22T21:30:00Z',
      'evidence_refs': <String>[],
    };
    stations.add(newcomer);

    current = await syntheticSignature(next, temporaryKey, verifier, previous: v5);
    final second = await selector.select(client: remote,
        favoriteIds: [], allowNetwork: true);
    expect(second, isNotNull);
    expect(second!.signedSequence, 6);
    expect(second.stations, hasLength(310));
    expect(second.stations.any((s) =>
        s.id == 'go-station-901000'), isTrue);
    expect(second.stations.singleWhere((s) => s.name == 'HardRadio').streamUrl,
        'https://new-radio-stream.example.org/hardradio.mp3');
    final imageRow = second.snapshot.stations.firstWhere((s) =>
        s['go_station_id'] == withLogo['go_station_id']);
    expect((imageRow['logo'] as Map<String, dynamic>)['sha256'], replacementSha);
    final changedArtworkStation = second.stations.firstWhere((s) {
      final owner = second.snapshot.aliasOwners[s.id] ?? s.id;
      return owner == withLogo['go_station_id'];
    });
    expect(changedArtworkStation.logoUrl,
        'https://cdn.example.org/new-verified-logo.png');
    expect(changedArtworkStation.logoSource, 'central-signed-sha-only');

    // New signed v6 remains available with the same installed client offline.
    final offline = await selector.select(
        client: testedClient(tempFolder, verifier, () => current,
            networkError: true), favoriteIds: []);
    expect(offline!.signedSequence, 6);
    expect(offline.stations, hasLength(310));
  }, skip: !fixture.existsSync());
}
