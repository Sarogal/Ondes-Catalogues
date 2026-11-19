// Android Auto HTTPS PNG diagnostic. Entry point is NEVER imported from main.dart.
// Only compiled by GO_HTTPS_ISOLATED_DEBUG side-by-side Android Debug builds.
// No production radio, real station ID, favorites, player or Play-store cache.
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:audio_service/audio_service.dart';
import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart' show kReleaseMode, debugPrint, ValueNotifier;
import 'package:flutter/widgets.dart';

import '../android_auto_artwork_uris.dart';
import '../central_android_auto_artwork_index.dart';
import '../central_logo_android_auto_bridge.dart';
import '../central_logo_asset_store.dart';
import '../central_logo_http_fetcher.dart';
import '../central_logo_prefetch_executor.dart';
import '../central_logo_preparation_plan.dart';
import '../central_radio_catalog_core.dart';
import 'central_android_auto_diagnostic_handler.dart';

const bool goHttpsDiagnosticEnabled = bool.fromEnvironment(
  'GO_HTTPS_DIAGNOSTIC', defaultValue: false,
);
const String httpsDiagnosticAuthority =
    'fr.grossesondes.grosses_ondes.dhunetdiag.stationlogos';

// Immutable Git commit with two synthetic, non-radio PNG files.
// These fixtures are not fetched from, or published to, the GO production CDN.
const String _fixtureRoot =
    'https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/'
    '2a31215f6f8e101e8b1f1000dc38b1b7a788e628/'
    'radio-catalog-lab/fixtures/';

CentralLogoDescriptor httpsDiagnosticLogo(int revision) {
  if (revision != 1 && revision != 2) {
    throw ArgumentError.value(revision, 'revision', 'Expected 1 or 2');
  }
  final first = revision == 1;
  return CentralLogoDescriptor(
    sha256: first
        ? '0e3073fc00b4c24524db33279dad8c7669285d80e9f27cc4a220371e7921e625'
        : '65d0a5219636e337bdc2ee97e458628722eb0f2d96be98c00b9804913fe70e1c',
    byteSize: 181,
    revision: revision,
    url: _fixtureRoot + 'logo_https_lab_v' + revision.toString() + '.png',
    width: 64,
    height: 64,
    mimeType: 'image/png',
  );
}

Uint8List _jsonBytes(Object value) =>
    Uint8List.fromList(utf8.encode(jsonEncode(value)));

Map<String, dynamic> _station(int number, CentralLogoDescriptor? logo) {
  final id = 'https-lab-' + number.toString();
  return <String, dynamic>{
    'go_station_id': 'go-station-' + number.toString().padLeft(6, '0'),
    'display_name': 'HTTPS laboratory image ' + number.toString(),
    'country_code': 'FR',
    'genres': <String>['Punk'],
    'tags': <String>['Punk'],
    'homepage': 'https://example.org',
    'radio_browser_uuids': <Map<String, dynamic>>[
      <String, dynamic>{'uuid': id, 'state': 'historical'},
    ],
    'legacy_aliases': <String>[id],
    'status': <String, dynamic>{
      'state': 'active', 'reason_code': null,
      'changed_at': '2026-11-19T05:00:00Z',
    },
    'streams': <Map<String, dynamic>>[
      <String, dynamic>{
        'stream_id': 'offline-' + id,
        'url': 'https://example.org/never-play.mp3',
        'priority': 0, 'protocol': 'https', 'codec': 'mp3',
        'bitrate_kbps': 128, 'state': 'verified',
      },
    ],
    'logo': logo == null ? null : <String, dynamic>{
      'asset_id': 'sha256:' + logo.sha256,
      'sha256': logo.sha256,
      'byte_size': logo.byteSize,
      'revision': logo.revision,
      'url': logo.url,
      'width': logo.width,
      'height': logo.height,
      'mime_type': logo.mimeType,
    },
    'editorial': <String, dynamic>{
      'admission_state': 'approved',
      'reviewed_at': '2026-11-19T05:00:00Z',
      'evidence_refs': <String>[],
    },
  };
}

/// Sign a TEST-ONLY fake catalog with an ephemeral key, then verify it with
/// the real production verifier. Never writes private keys or a catalog file.
Future<ValidatedCentralCatalog> makeHttpsDiagnosticSignedCatalog() async {
  final pair = await Ed25519().newKeyPair();
  final publicKey = await pair.extractPublicKey();
  final verifier = CentralCatalogVerifier(
    trustedKeys: <String, SimplePublicKey>{'https-diagnostic-only': publicKey},
  );
  final bytes = _jsonBytes(<String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'generated_at': '2026-11-19T05:00:00Z',
    'stations': <Map<String, dynamic>>[
      _station(1, httpsDiagnosticLogo(1)),
      _station(2, httpsDiagnosticLogo(2)),
      _station(3, null),
    ],
    'tombstones': <dynamic>[],
  });
  final digest = crypto.sha256.convert(bytes).toString();
  final pointer = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-19T05:00:00Z',
    'content_sha256': digest,
    'content_length': bytes.length,
    'content_path': 'releases/' + digest + '.json',
    'signature': <String, dynamic>{
      'algorithm': 'Ed25519',
      'key_id': 'https-diagnostic-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0)),
    },
  };
  final sig = await Ed25519().sign(
    CentralCatalogPointer.parse(_jsonBytes(pointer)).signatureMessage,
    keyPair: pair,
  );
  (pointer['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(sig.bytes);
  return verifier.verify(
    pointerBytes: _jsonBytes(pointer), catalogBytes: bytes,
  );
}

class HttpsDiagnosticProof {
  const HttpsDiagnosticProof({
    required this.catalog,
    required this.index,
    required this.networkFetches,
    required this.offlineOldFallbackChecked,
    required this.replayFetches,
  });
  final ValidatedCentralCatalog catalog;
  final CentralAndroidAutoArtworkIndex index;
  final int networkFetches;
  final bool offlineOldFallbackChecked;
  final int replayFetches;
}

CentralLogoPreparationPlan _singleImagePlan(
  CentralLogoDescriptor descriptor,
) => CentralLogoPreparationPlan(
  items: <CentralLogoPreparationItem>[
    CentralLogoPreparationItem(
      descriptor: descriptor,
      stationIds: const <String>['go-station-000001'],
    ),
  ],
  activeWithoutLogo: const <String>[],
  excludedInactive: const <String>[],
);

/// Shared testable, explicit opt-in workflow. Network is limited to exactly
/// the two pinned fixture URLs, not merely any path on the permitted host.
/// V1 is installed before checking the offline fallback for the not-yet-
/// installed V2. V2 is installed separately, never deleting V1.
Future<HttpsDiagnosticProof> prepareHttpsDiagnostic({
  required CentralLogoAssetStore store,
  required CentralLogoBytesFetcher fetch,
  Future<ValidatedCentralCatalog> Function()? verifiedCatalog,
  Future<CentralAndroidAutoArtworkIndex> Function(
    ValidatedCentralCatalog, CentralLogoAssetStore,
  )? buildArtworkIndex,
}) async {
  final v1 = httpsDiagnosticLogo(1);
  final v2 = httpsDiagnosticLogo(2);
  var transfers = 0;
  Future<Uint8List> pinnedFetcher(Uri uri, int bytes) async {
    final allowed = <String>{v1.url, v2.url};
    if (!allowed.contains(uri.toString()) || bytes != 181) {
      throw const CentralCatalogException(
        'Refusing unpinned HTTPS diagnostic URL',
      );
    }
    transfers++;
    return fetch(uri, bytes);
  }

  final catalog = await (verifiedCatalog ??
      makeHttpsDiagnosticSignedCatalog)();
  final plan = const CentralLogoPreparationPlanner().plan(catalog);
  if (plan.uniqueImageCount != 2 || plan.activeWithoutLogo.length != 1 ||
      plan.items.map((item) => item.descriptor.sha256).toSet()
          .difference(<String>{v1.sha256, v2.sha256}).isNotEmpty) {
    throw const CentralCatalogException('HTTPS fixture catalog mismatch');
  }

  final policy = CentralLogoPrefetchPolicy(
    allowNetwork: true,
    allowedHosts: const <String>{'raw.githubusercontent.com'},
    maxObjects: 1,
    maxBytes: 181,
  );
  final executor = CentralLogoPrefetchExecutor();
  Future<void> install(CentralLogoDescriptor descriptor) async {
    final report = await executor.execute(
      plan: _singleImagePlan(descriptor),
      store: store,
      policy: policy,
      fetch: pinnedFetcher,
    );
    final outcome = report.entries.single.outcome;
    if (outcome != CentralLogoPrefetchOutcome.downloaded &&
        outcome != CentralLogoPrefetchOutcome.cached) {
      throw CentralCatalogException(
        'HTTPS laboratory image was not verified: ' + outcome.name,
      );
    }
  }

  await install(v1);
  final old = await store.findVerified(v1);
  if (old == null) {
    throw const CentralCatalogException('Verified HTTPS V1 disappeared');
  }
  final offline = await store.ensure(target: v2, previous: v1);
  if (offline.status != CentralLogoCacheStatus.cacheHit &&
      (offline.status != CentralLogoCacheStatus.offline ||
       !offline.usedOlderLogo || offline.image?.path != old.path)) {
    throw const CentralCatalogException(
      'Unexpected offline transition between V1 and V2',
    );
  }
  await install(v2);
  if (await store.findVerified(v1) == null ||
      await store.findVerified(v2) == null) {
    throw const CentralCatalogException('HTTPS SHA objects did not persist');
  }

  // Prove a full same-store replay never invokes a supplied fetcher. On the
  // next application launch, the same checks repeat with a new store instance.
  var replayFetches = 0;
  for (final descriptor in <CentralLogoDescriptor>[v1, v2]) {
    final result = await CentralLogoPrefetchExecutor().execute(
      plan: _singleImagePlan(descriptor),
      store: store,
      policy: policy,
      fetch: (url, length) async {
        replayFetches++;
        throw StateError('Verified HTTPS SHA must never be re-fetched');
      },
    );
    if (result.entries.single.outcome != CentralLogoPrefetchOutcome.cached ||
        result.reservedAttempts != 0) {
      throw const CentralCatalogException('HTTPS SHA replay was not a cache hit');
    }
  }
  if (replayFetches != 0) {
    throw const CentralCatalogException('Unexpected diagnostic network replay');
  }

  final indexBuilder = buildArtworkIndex ??
      (ValidatedCentralCatalog catalog, CentralLogoAssetStore store) =>
          const CentralAndroidAutoArtworkIndexBuilder().prepare(
            catalog: catalog, store: store,
          );
  final index = await indexBuilder(catalog, store);
  if (index.verifiedCentralForStationId('https-lab-1') !=
          AndroidAutoArtworkUris.forCentralSha256(v1.sha256) ||
      index.verifiedCentralForStationId('https-lab-2') !=
          AndroidAutoArtworkUris.forCentralSha256(v2.sha256) ||
      index.verifiedCentralForStationId('https-lab-3') != null) {
    throw const CentralCatalogException('Android Auto HTTPS art mapping failed');
  }
  return HttpsDiagnosticProof(
    catalog: catalog,
    index: index,
    networkFetches: transfers,
    offlineOldFallbackChecked: offline.status == CentralLogoCacheStatus.offline,
    replayFetches: replayFetches,
  );
}

List<MediaItem> httpsDiagnosticMediaItems() {
  const browseContext = 'go:auto:all';
  final fallback = AndroidAutoArtworkUris.forGenre('Punk');
  return <MediaItem>[
    for (final n in <int>[1, 2, 3])
      MediaItem(
        id: 'go:auto:station:https-lab-' + n.toString() +
            '|' + Uri.encodeComponent(browseContext),
        title: n == 1
            ? 'HTTPS V1 - cache'
            : (n == 2
                ? 'HTTPS V2 - revision'
                : 'Vignette Punk secours'),
        album: 'Grosses Ondes - Diagnostic HTTPS',
        artist: 'Aucun flux audio',
        genre: 'Punk',
        playable: true,
        isLive: false,
        artUri: fallback,
        extras: <String, dynamic>{
          'stationId': 'https-lab-' + n.toString(),
          'browseContext': browseContext,
        },
      ),
  ];
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final status = ValueNotifier<String>(
    'GO HTTPS Diagnostic\nPreparation securisee des logos...'
  );
  runApp(Directionality(
    textDirection: TextDirection.ltr,
    child: Center(
      child: ValueListenableBuilder<String>(
        valueListenable: status,
        builder: (context, value, child) => Text(
          value,
          textAlign: TextAlign.center,
        ),
      ),
    ),
  ));
  try {
    if (!Platform.isAndroid || kReleaseMode || !goHttpsDiagnosticEnabled ||
        AndroidAutoArtworkUris.authority != httpsDiagnosticAuthority) {
      throw StateError('Isolated Android HTTPS DEBUG build required');
    }
    final store = await CentralLogoAndroidAutoBridge.createStore();
    final proof = await prepareHttpsDiagnostic(
      store: store,
      fetch: const CentralLogoHttpFetcher().fetch,
    );
    final items = httpsDiagnosticMediaItems();
    final handler = await AudioService.init<CentralAndroidAutoDiagnosticHandler>(
      builder: () => CentralAndroidAutoDiagnosticHandler(
        legacyItems: items,
        artworkIndex: proof.index,
        enableVerifiedArtwork: true,
        rootSubtitle: 'Images HTTPS de test, aucun audio',
      ),
      config: const AudioServiceConfig(
        androidNotificationChannelId:
            'fr.grossesondes.app.channel.audio.https_probe',
        androidNotificationChannelName: 'GO HTTPS Diagnostic',
        androidNotificationOngoing: false,
        androidStopForegroundOnPause: true,
        androidBrowsableRootExtras: <String, dynamic>{
          'android.media.browse.CONTENT_STYLE_SUPPORTED': true,
          'android.media.browse.CONTENT_STYLE_BROWSABLE_HINT': 1,
          'android.media.browse.CONTENT_STYLE_PLAYABLE_HINT': 1,
        },
      ),
    );
    final browse = await handler.getChildren(
      CentralAndroidAutoDiagnosticHandler.browseId,
    );
    final expected = <Uri>[
      AndroidAutoArtworkUris.forCentralSha256(httpsDiagnosticLogo(1).sha256),
      AndroidAutoArtworkUris.forCentralSha256(httpsDiagnosticLogo(2).sha256),
      AndroidAutoArtworkUris.forGenre('Punk'),
    ];
    if (browse.length != 3 ||
        browse.asMap().entries.any((entry) =>
            entry.value.artUri != expected[entry.key]) ||
        handler.playbackState.value.playing) {
      throw const CentralCatalogException('MediaBrowser HTTPS fixture mismatch');
    }
    status.value = 'GO HTTPS Diagnostic : VALIDE\n'
        'HTTPS telechargements : ' + proof.networkFetches.toString() + '\n'
        'SHA V1 et V2 verifies, 3 vignettes Android Auto\n'
        'Flux audio : aucun';
    debugPrint('GO_HTTPS_PHONE_READY networkFetches=' +
        proof.networkFetches.toString() +
        ' offlineOldFallback=' + proof.offlineOldFallbackChecked.toString() +
        ' replayFetches=' + proof.replayFetches.toString() +
        ' images=3 playing=false');
  } catch (error) {
    status.value = 'GO HTTPS Diagnostic : ECHEC\n'
        'Controle HTTPS non valide : ' + error.runtimeType.toString() +
        '\nNe rien reinstaller ni effacer';
    debugPrint('GO_HTTPS_PHONE_FAIL ' + error.runtimeType.toString() +
        ' ' + error.toString());
  }
}
