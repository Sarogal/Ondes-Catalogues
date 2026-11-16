// DEBUG TARGET ONLY: native Flutter -> SHA store -> Android ContentProvider.
// Not imported by lib/main.dart, RootShell, audio handlers or the V64 catalog.
// Uses a packaged Punk PNG and an ephemeral, test-only Ed25519 signing key.
// No HTTP sockets and no mutation of live station/favorite preferences.
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:flutter/widgets.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import '../central_flutter_logo_decoder.dart';
import '../central_logo_android_auto_bridge.dart';
import '../central_logo_asset_store.dart';
import '../central_logo_prefetch_executor.dart';
import '../central_radio_catalog_client.dart';
import '../central_radio_catalog_core.dart';
import '../central_verified_logo_workflow.dart';

const _snapshotsDirName = 'grosses_ondes_debug_probe_snapshots_v1';
const _testHost = 'images.example.org';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const Directionality(
    textDirection: TextDirection.ltr,
    child: Center(
      child: Text('Grosses Ondes - sonde Flutter / logos Android (DEBUG)'),
    ),
  ));
  try {
    await _runIsolatedProbe();
  } catch (error) {
    debugPrint('GO_CENTRAL_PROBE FAIL ${error.runtimeType}');
  }
}

Uint8List _jsonBytes(Object value) =>
    Uint8List.fromList(utf8.encode(jsonEncode(value)));

Map<String, dynamic> _station(int index, Map<String, dynamic> signedLogo) {
  final id = 'go-station-${index.toString().padLeft(6, '0')}';
  return {
    'go_station_id': id,
    'display_name': 'Debug-only radio $index',
    'country_code': 'FR',
    'genres': ['Punk'],
    'tags': ['Punk'],
    'homepage': 'https://example.org',
    'radio_browser_uuids': [
      {'uuid': 'diagnostic-legacy-$index', 'state': 'historical'},
    ],
    'legacy_aliases': ['diagnostic-legacy-$index'],
    'status': {
      'state': 'active',
      'reason_code': null,
      'changed_at': '2026-11-16T21:00:00Z',
    },
    'streams': [
      {
        'stream_id': 'debug-stream-$index',
        'url': 'https://example.org/debug-only-$index.mp3',
        'priority': 0,
        'protocol': 'https',
        'codec': 'mp3',
        'bitrate_kbps': 128,
        'state': 'verified',
      }
    ],
    'logo': signedLogo,
    'editorial': {
      'admission_state': 'approved',
      'reviewed_at': '2026-11-16T21:00:00Z',
      'evidence_refs': [],
    },
  };
}

Future<void> _runIsolatedProbe() async {
  if (!Platform.isAndroid || kReleaseMode) {
    // This entrypoint must never be used on a release build or non-Android OS.
    throw StateError('Debug Android emulator probe only');
  }

  final asset = await rootBundle.load('assets/genres/punk.png');
  final png = asset.buffer.asUint8List(asset.offsetInBytes, asset.lengthInBytes);
  final decoded = await decodeCentralFlutterLogo(png);
  if (decoded.mimeType != 'image/png' || png.isEmpty || png.length > 8 * 1024 * 1024) {
    throw StateError('Packaged Punk PNG not usable');
  }
  final digest = crypto.sha256.convert(png).toString();
  final support = await getApplicationSupportDirectory();
  final snapshotsDir = Directory('${support.path}/$_snapshotsDirName');
  final store = await CentralLogoAndroidAutoBridge.createStore();
  final target = File('${store.directory.path}/$digest.img');
  if (await snapshotsDir.exists() || await target.exists()) {
    throw StateError('Refusing to reuse or overwrite previous probe data');
  }

  // Only a synthetic catalog: no production public/private signing keys.
  final signingPair = await Ed25519().newKeyPair();
  final publicKey = await signingPair.extractPublicKey();
  final verifier = CentralCatalogVerifier(
    trustedKeys: {'debug-emulator-only': publicKey},
  );
  final logo = <String, dynamic>{
    'asset_id': 'sha256:$digest',
    'sha256': digest,
    'byte_size': png.length,
    'revision': 1,
    'url': 'https://$_testHost/debug-only-punk.png',
    'width': decoded.width,
    'height': decoded.height,
    'mime_type': decoded.mimeType,
  };
  final catalogBytes = _jsonBytes({
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'generated_at': '2026-11-16T21:00:00Z',
    'stations': [_station(1, logo), _station(2, logo)],
    'tombstones': [],
  });
  final catalogDigest = crypto.sha256.convert(catalogBytes).toString();
  final pointer = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-16T21:00:00Z',
    'content_sha256': catalogDigest,
    'content_length': catalogBytes.length,
    'content_path': 'releases/$catalogDigest.json',
    'signature': {
      'algorithm': 'Ed25519',
      'key_id': 'debug-emulator-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0)),
    },
  };
  final signed = await Ed25519().sign(
    CentralCatalogPointer.parse(_jsonBytes(pointer)).signatureMessage,
    keyPair: signingPair,
  );
  (pointer['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(signed.bytes);
  final signedPointer = _jsonBytes(pointer);
  final snapshot = await verifier.verify(
    pointerBytes: signedPointer,
    catalogBytes: catalogBytes,
  );
  final disk = CentralCatalogDiskStore(snapshotsDir);
  await disk.persist(snapshot);

  CentralVerifiedLogoWorkflow createWorkflow(CentralLogoAssetStore cache) =>
      CentralVerifiedLogoWorkflow(
        disk: disk,
        verifier: verifier,
        store: cache,
      );

  final initial = await createWorkflow(store).inspectOffline();
  if (initial == null ||
      initial.plan.uniqueImageCount != 1 ||
      initial.plan.representedStationCount != 2 ||
      initial.inspection.missingObjects != 1) {
    throw StateError('Signed catalog projection was not verified');
  }
  var requests = 0;
  final policy = CentralLogoPrefetchPolicy(
    allowNetwork: true,
    allowedHosts: const {_testHost},
    maxObjects: 1,
    maxBytes: png.length,
  );
  Future<Uint8List> injectedBytes(Uri uri, int maxBytes) async {
    if (uri.host != _testHost || maxBytes != png.length) {
      throw StateError('Unexpected image endpoint');
    }
    requests++;
    return png; // No HTTP, network is simulated with bundled bytes.
  }

  final first = await createWorkflow(store).prefetchExplicit(
    policy: policy,
    fetch: injectedBytes,
  );
  if (first?.report.downloadedObjects != 1 || requests != 1) {
    throw StateError('First SHA installation failed');
  }
  final descriptor = CentralLogoDescriptor.fromSignedStation(
    snapshot.stations.first,
  )!;
  final uri = await CentralLogoAndroidAutoBridge.verifiedArtworkUri(
    store: store,
    descriptor: descriptor,
  );
  if (uri == null || uri.pathSegments.length != 2 ||
      uri.pathSegments.first != 'central') {
    throw StateError('Verified Android Auto URI unavailable');
  }

  final reloadedStore = await CentralLogoAndroidAutoBridge.createStore();
  final second = await createWorkflow(reloadedStore).prefetchExplicit(
    policy: policy,
    fetch: injectedBytes,
  );
  if (second?.report.cachedObjects != 1 ||
      second?.report.reservedAttempts != 0 ||
      requests != 1) {
    throw StateError('Repeat launch would download identical SHA');
  }
  final local = await reloadedStore.findVerified(descriptor);
  if (local == null || !await local.exists()) {
    throw StateError('Verified permanent image not on disk');
  }
  // The separate host-side probe reads these same bytes from Kotlin's provider.
  debugPrint('GO_CENTRAL_PROBE PASS sha=$digest requests=$requests stations=2 uri=$uri');
}
