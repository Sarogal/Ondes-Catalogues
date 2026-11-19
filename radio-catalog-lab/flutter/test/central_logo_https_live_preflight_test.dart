import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:crypto/crypto.dart' as crypto;
import 'package:go_radio_flutter_lab/central_flutter_logo_decoder.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_logo_http_fetcher.dart';
import 'package:go_radio_flutter_lab/central_logo_prefetch_executor.dart';
import 'package:go_radio_flutter_lab/central_logo_preparation_plan.dart';

// OFF by default, never used at app startup or by public V64.
// Opt in only in the isolated CI / diagnostic worktree:
// flutter test --dart-define=GO_HTTPS_LOGO_PREFLIGHT=true test/central_logo_https_live_preflight_test.dart
const enabled = bool.fromEnvironment('GO_HTTPS_LOGO_PREFLIGHT', defaultValue: false);

// Immutable commit in the public LAB branch, not Github Pages, not a
// radio's copyrighted logo, not a release or production endpoint.
// Both are real, independently decoded 64x64 PNGs served over HTTPS.
const root = 'https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/'
    '2a31215f6f8e101e8b1f1000dc38b1b7a788e628/radio-catalog-lab/fixtures/';

CentralLogoDescriptor descriptor(int revision) {
  final first = revision == 1;
  assert(revision == 1 || revision == 2);
  return CentralLogoDescriptor(
    sha256: first
        ? '0e3073fc00b4c24524db33279dad8c7669285d80e9f27cc4a220371e7921e625'
        : '65d0a5219636e337bdc2ee97e458628722eb0f2d96be98c00b9804913fe70e1c',
    byteSize: 181,
    revision: revision,
    url: '${root}logo_https_lab_v${revision}.png',
    width: 64,
    height: 64,
    mimeType: 'image/png',
  );
}

CentralLogoPreparationPlan oneLogo(CentralLogoDescriptor spec) =>
    CentralLogoPreparationPlan(
      items: [
        CentralLogoPreparationItem(
          descriptor: spec,
          stationIds: const ['go-station-000001', 'go-station-000002'],
        ),
      ],
      activeWithoutLogo: const [],
      excludedInactive: const [],
    );

// Restores real TLS clients inside the opt-in test zone, leaving all other
// flutter_test HTTP mocks and production settings untouched.
class _RealNetworkHttpOverrides extends HttpOverrides {}

void main() {
  test('real HTTPS v1 -> offline restart -> revision v2, preserving v1', () async {
    // flutter_test mocks HttpClient by default. This explicit opt-in test
    // temporarily enables real TLS, then restores the test environment.
    await HttpOverrides.runWithHttpOverrides(() async {
    final temp = await Directory.systemTemp.createTemp('go-https-sha-lab-');
    try {
      final v1 = descriptor(1);
      final v2 = descriptor(2);
      final directory = Directory('${temp.path}/central');
      CentralLogoAssetStore store() => CentralLogoAssetStore(
        directory: directory,
        decoder: decodeCentralFlutterLogo,
      );
      final fetcher = const CentralLogoHttpFetcher();
      final policy = CentralLogoPrefetchPolicy(
        allowNetwork: true,
        allowedHosts: const {'raw.githubusercontent.com'},
        maxObjects: 1,
        maxBytes: 2048,
      );

      // FIRST AND ONLY v1 HTTPS transfer through the real bounded fetcher.
      final first = await CentralLogoPrefetchExecutor().execute(
        plan: oneLogo(v1),
        store: store(),
        policy: policy,
        fetch: fetcher.fetch,
      );
      if (first.entries.single.outcome != CentralLogoPrefetchOutcome.downloaded) {
        // The store deliberately hides transport exceptions; recover the
        // diagnostic reason via an explicit HTTPS read for this LAB only.
        try {
          final probe = await fetcher.fetch(Uri.parse(v1.url), v1.byteSize);
          print('GO_HTTPS_DIAGNOSTIC direct_len=${probe.length} '
              'direct_sha=${crypto.sha256.convert(probe)} '
              'url_host=${Uri.parse(v1.url).host}');
        } catch (error) {
          print('GO_HTTPS_DIAGNOSTIC failed=$error '
              'override=${HttpOverrides.current.runtimeType}');
        }
      }
      expect(first.entries.single.outcome, CentralLogoPrefetchOutcome.downloaded);
      expect(first.reservedAttempts, 1);
      expect(first.reservedBytes, 181);
      final original = first.entries.single.file!;
      final originalBytes = await original.readAsBytes();
      expect(originalBytes.length, 181);
      expect(crypto.sha256.convert(originalBytes).toString(), v1.sha256);
      expect(await store().findVerified(v1), isNotNull);

      // "Network allowed" but v1 is already verified: ZERO fetcher calls.
      // Recreate the store to mimic app/service restart.
      var unintendedFetchCalls = 0;
      Future<Uint8List> mustNotFetch(Uri _, int __) async {
        unintendedFetchCalls++;
        throw StateError('A verified SHA must never be downloaded again');
      }
      final cached = await CentralLogoPrefetchExecutor().execute(
        plan: oneLogo(v1),
        store: store(),
        policy: policy,
        fetch: mustNotFetch,
      );
      expect(cached.entries.single.outcome, CentralLogoPrefetchOutcome.cached);
      expect(cached.reservedAttempts, 0);
      expect(unintendedFetchCalls, 0);

      // A new signed SHA is known, but it is OFFLINE: retain previous image.
      final offline = await store().ensure(
        target: v2,
        previous: v1,
      );
      expect(offline.status, CentralLogoCacheStatus.offline);
      expect(offline.usedOlderLogo, isTrue);
      expect(offline.image!.path, original.path);
      expect(await offline.image!.readAsBytes(), originalBytes);

      // New revision: another real HTTPS request; new content-addressed
      // object, never overwrite or delete the previous trusted image.
      final changed = await store().ensure(
        target: v2,
        previous: v1,
        fetch: fetcher.fetch,
      );
      expect(changed.status, CentralLogoCacheStatus.downloaded);
      expect(changed.usedOlderLogo, isFalse);
      final nextBytes = await changed.image!.readAsBytes();
      expect(nextBytes.length, 181);
      expect(crypto.sha256.convert(nextBytes).toString(), v2.sha256);
      expect(changed.image!.path, isNot(original.path));
      expect(await original.readAsBytes(), originalBytes);

      // After a second restart, v2 remains reusable entirely offline.
      final offlineAgain = await store().ensure(target: v2);
      expect(offlineAgain.status, CentralLogoCacheStatus.cacheHit);
      expect(offlineAgain.image!.path, changed.image!.path);
      expect(await store().findVerified(v1), isNotNull);
      print('GO_LAB_REAL_HTTPS_PASS v1=${v1.sha256} v2=${v2.sha256} '
          'bytes_v1=${v1.byteSize} bytes_v2=${v2.byteSize} '
          'offline_cache_hit=true older_sha_preserved=true');
    } finally {
      if (await temp.exists()) await temp.delete(recursive: true);
    }
    }, _RealNetworkHttpOverrides());
  }, skip: !enabled);
}
