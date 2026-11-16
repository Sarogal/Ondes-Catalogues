import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_logo_prefetch_executor.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_client.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';
import 'package:go_radio_flutter_lab/central_verified_logo_workflow.dart';

Uint8List bytes(int seed) => Uint8List.fromList(
      List<int>.generate(128, (index) => (index + seed) & 255),
    );

Uint8List encode(Object value) => Uint8List.fromList(utf8.encode(jsonEncode(value)));

Map<String, dynamic> station(
  int index, {
  String status = 'active',
  Uint8List? logo,
}) {
  final id = 'go-station-${index.toString().padLeft(6, '0')}';
  final digest = logo == null ? null : crypto.sha256.convert(logo).toString();
  return {
    'go_station_id': id,
    'display_name': 'Test-only radio $index',
    'country_code': 'FR',
    'genres': ['Heavy'],
    'homepage': 'https://example.org',
    'tags': ['Heavy'],
    'radio_browser_uuids': [
      {'uuid': 'legacy-$index', 'state': 'historical'},
    ],
    'legacy_aliases': ['legacy-$index'],
    'status': {
      'state': status,
      'reason_code': status == 'active' ? null : 'manual_editorial_decision',
      'changed_at': '2026-11-16T18:00:00Z',
    },
    'streams': [
      {
        'stream_id': 'stream-$index',
        'url': 'https://example.org/audio-$index.mp3',
        'priority': 0,
        'protocol': 'https',
        'codec': 'mp3',
        'bitrate_kbps': 128,
        'state': 'verified',
      },
    ],
    'logo': digest == null
        ? null
        : {
            'sha256': digest,
            'asset_id': 'sha256:$digest',
            'byte_size': logo!.length,
            'revision': 1,
            'url': 'https://images.example.org/$digest.png',
            'width': 512,
            'height': 512,
            'mime_type': 'image/png',
          },
    'editorial': {
      'admission_state': 'approved',
      'reviewed_at': '2026-11-16T18:00:00Z',
      'evidence_refs': [],
    },
  };
}

Future<CentralCatalogPointer> unsignedPointer(
  Map<String, dynamic> document,
) async => CentralCatalogPointer.parse(encode(document));

Future<Uint8List> signedPointer(Uint8List payload, KeyPair keyPair) async {
  final digest = crypto.sha256.convert(payload).toString();
  final value = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-16T18:00:00Z',
    'content_sha256': digest,
    'content_length': payload.length,
    'content_path': 'releases/$digest.json',
    'signature': {
      'algorithm': 'Ed25519',
      'key_id': 'test-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0)),
    },
  };
  final message = (await unsignedPointer(value)).signatureMessage;
  final signature = await Ed25519().sign(message, keyPair: keyPair);
  (value['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(signature.bytes);
  return encode(value);
}

Future<CentralDecodedLogo> decoder(Uint8List _) async =>
    const CentralDecodedLogo(
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

void main() {
  late Directory temporary;
  late KeyPair keyPair;
  late CentralCatalogVerifier verifier;
  late CentralCatalogDiskStore disk;
  late CentralLogoAssetStore store;

  setUpAll(() async {
    keyPair = await Ed25519().newKeyPair();
    final publicKey = (await keyPair.extractPublicKey()) as SimplePublicKey;
    verifier = CentralCatalogVerifier(trustedKeys: {'test-only': publicKey});
  });

  setUp(() async {
    temporary = await Directory.systemTemp.createTemp('go-verified-logo-flow-');
    disk = CentralCatalogDiskStore(
      Directory('${temporary.path}/snapshots'),
    );
    store = CentralLogoAssetStore(
      directory: Directory('${temporary.path}/logos'),
      decoder: decoder,
    );
  });
  tearDown(() async {
    if (await temporary.exists()) await temporary.delete(recursive: true);
  });

  Future<void> persistSigned(List<Map<String, dynamic>> stations) async {
    final payload = encode({
      'schema_version': 1,
      'catalog_id': 'grosses-ondes-radio',
      'release_sequence': 1,
      'generated_at': '2026-11-16T18:00:00Z',
      'stations': stations,
      'tombstones': [],
    });
    final pointerBytes = await signedPointer(payload, keyPair);
    final snapshot = await verifier.verify(
      pointerBytes: pointerBytes,
      catalogBytes: payload,
    );
    await disk.persist(snapshot);
  }

  CentralVerifiedLogoWorkflow workflow({
    CentralCatalogVerifier? trust,
    CentralLogoAssetStore? cache,
  }) =>
      CentralVerifiedLogoWorkflow(
        disk: disk,
        verifier: trust ?? verifier,
        store: cache ?? store,
      );

  test('no signed snapshot means no plan, network or image writes', () async {
    final flow = workflow();
    expect(await flow.inspectOffline(), isNull);
    expect(await flow.prefetchExplicit(), isNull);
    expect(await store.directory.exists(), isFalse);
    expect(await disk.directory.exists(), isFalse);
  });

  test('authenticated snapshot yields one SHA for two active radios', () async {
    final shared = bytes(1);
    await persistSigned([
      station(1, logo: shared),
      station(2, logo: shared),
      station(3, logo: bytes(2), status: 'quarantined'),
      station(4),
    ]);
    final state = await workflow().inspectOffline();
    expect(state, isNotNull);
    expect(state!.catalog.pointer.sequence, 1);
    expect(state.plan.uniqueImageCount, 1);
    expect(state.plan.representedStationCount, 2);
    expect(state.plan.excludedInactive, ['go-station-000003']);
    expect(state.plan.activeWithoutLogo, ['go-station-000004']);
    expect(state.inspection.cachedObjects, 0);
    expect(state.inspection.missingObjects, 1);
    expect(state.inspection.missingBytes, shared.length);
    expect(await store.directory.exists(), isFalse);
  });

  test('explicit call remains offline even when supplied a fetcher', () async {
    final sample = bytes(3);
    await persistSigned([station(1, logo: sample)]);
    var requests = 0;
    final result = await workflow().prefetchExplicit(
      fetch: (uri, limit) async {
        requests++;
        return sample;
      },
    );
    expect(result, isNotNull);
    expect(result!.report.entries.single.outcome,
        CentralLogoPrefetchOutcome.offline);
    expect(result.report.reservedAttempts, 0);
    expect(requests, 0);
    expect(await store.directory.exists(), isFalse);
  });

  test('explicit policy installs once, next run is a verified disk hit',
      () async {
    final sample = bytes(4);
    await persistSigned([
      station(1, logo: sample),
      station(2, logo: sample),
    ]);
    var requests = 0;
    final flow = workflow();
    final policy = CentralLogoPrefetchPolicy(
      allowNetwork: true,
      allowedHosts: const {'images.example.org'},
      maxObjects: 1,
      maxBytes: 128,
    );
    Future<Uint8List> fetch(Uri uri, int limit) async {
      requests++;
      expect(uri.host, 'images.example.org');
      return sample;
    }

    final first = await flow.prefetchExplicit(policy: policy, fetch: fetch);
    expect(first, isNotNull);
    expect(first!.report.downloadedObjects, 1);
    expect(first.plan.representedStationCount, 2);
    expect(first.report.reservedAttempts, 1);

    final restart = workflow();
    final cached = await restart.prefetchExplicit(policy: policy, fetch: fetch);
    expect(cached!.report.cachedObjects, 1);
    expect(cached.report.reservedAttempts, 0);
    expect(requests, 1);
    final inspected = await restart.inspectOffline();
    expect(inspected!.inspection.cachedObjects, 1);
    expect(inspected.inspection.cachedStationEntries, 2);
  });

  test('untrusted signer is not allowed to plan or download', () async {
    await persistSigned([station(1, logo: bytes(5))]);
    var requests = 0;
    final untrusted = workflow(
      trust: const CentralCatalogVerifier(trustedKeys: {}),
    );
    final control = CentralLogoPrefetchPolicy(
      allowNetwork: true,
      allowedHosts: const {'images.example.org'},
    );
    expect(await untrusted.inspectOffline(), isNull);
    expect(
      await untrusted.prefetchExplicit(
        policy: control,
        fetch: (uri, maxBytes) async {
          requests++;
          return bytes(5);
        },
      ),
      isNull,
    );
    expect(requests, 0);
    expect(await store.directory.exists(), isFalse);
  });

  test('tampered offline snapshot cannot cause prefetch', () async {
    await persistSigned([station(1, logo: bytes(6))]);
    final candidates = await disk.directory.list().where((e) => e is File).toList();
    expect(candidates, hasLength(1));
    final file = candidates.single as File;
    final data = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    final damaged = Uint8List.fromList(base64.decode(data['catalog_base64'] as String));
    damaged[damaged.length - 2] ^= 1;
    data['catalog_base64'] = base64.encode(damaged);
    await file.writeAsString(jsonEncode(data), flush: true);
    var requests = 0;
    final result = await workflow().prefetchExplicit(
      policy: CentralLogoPrefetchPolicy(
        allowNetwork: true,
        allowedHosts: const {'images.example.org'},
      ),
      fetch: (uri, maxBytes) async {
        requests++;
        return bytes(6);
      },
    );
    expect(result, isNull);
    expect(requests, 0);
    expect(await store.directory.exists(), isFalse);
  });
}
