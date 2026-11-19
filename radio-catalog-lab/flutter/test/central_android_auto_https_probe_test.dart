import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/diagnostics/central_android_auto_https_probe.dart';
import 'package:go_radio_flutter_lab/android_auto_artwork_uris.dart';
import 'package:go_radio_flutter_lab/central_android_auto_artwork_index.dart';
import 'package:go_radio_flutter_lab/central_flutter_logo_decoder.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_logo_http_fetcher.dart';

const bool live = bool.fromEnvironment(
  'GO_HTTPS_ANDROID_PROBE_PREFLIGHT', defaultValue: false,
);

class _RealNetworkHttpOverrides extends HttpOverrides {}

Future<CentralAndroidAutoArtworkIndex> localTestIndex(
  catalog,
  CentralLogoAssetStore store,
) => CentralAndroidAutoArtworkIndexBuilder(
  verifyLocalArtwork: ({required store, required descriptor}) async =>
      await store.findVerified(descriptor) == null
          ? null
          : AndroidAutoArtworkUris.forCentralSha256(descriptor.sha256),
).prepare(catalog: catalog, store: store);

void main() {
  test('HTTPS diagnostic must be compile-time disabled by default', () {
    expect(goHttpsDiagnosticEnabled, isFalse);
    expect(httpsDiagnosticAuthority,
        'fr.grossesondes.grosses_ondes.dhunetdiag.stationlogos');
    expect(httpsDiagnosticAuthority,
        isNot('fr.grossesondes.grosses_ondes.stationlogos'));
  });

  test('only two immutable, synthetic GitHub lab images are accepted', () {
    final v1 = httpsDiagnosticLogo(1);
    final v2 = httpsDiagnosticLogo(2);
    expect(v1.revision, 1);
    expect(v2.revision, 2);
    expect(v1.byteSize, 181);
    expect(v2.byteSize, 181);
    expect(v1.sha256, isNot(v2.sha256));
    expect(Uri.parse(v1.url).host, 'raw.githubusercontent.com');
    expect(Uri.parse(v2.url).host, 'raw.githubusercontent.com');
    expect(v1.url, contains('2a31215f6f8e101e8b1f1000dc38b1b7a788e628'));
    expect(v2.url, contains('2a31215f6f8e101e8b1f1000dc38b1b7a788e628'));
    expect(() => httpsDiagnosticLogo(3), throwsArgumentError);
  });

  test('ephemerally signed diagnostic catalog verifies three fake stations',
      () async {
    final signed = await makeHttpsDiagnosticSignedCatalog();
    expect(signed.stations, hasLength(3));
    expect(signed.stations[0]['legacy_aliases'], ['https-lab-1']);
    expect(signed.stations[1]['legacy_aliases'], ['https-lab-2']);
    expect(signed.stations[2]['logo'], isNull);
    expect(signed.stations[0]['logo']['sha256'], httpsDiagnosticLogo(1).sha256);
    expect(signed.stations[1]['logo']['sha256'], httpsDiagnosticLogo(2).sha256);
  });

  test('HTTPS entries are only silent metadata, with genre fallback', () {
    final items = httpsDiagnosticMediaItems();
    expect(items, hasLength(3));
    expect(items[0].title, 'HTTPS V1 - cache');
    expect(items[1].title, 'HTTPS V2 - revision');
    expect(items[2].title, 'Vignette Punk secours');
    expect(items.every((item) => item.artist == 'Aucun flux audio'), isTrue);
    expect(items.every((item) =>
      item.artUri == AndroidAutoArtworkUris.forGenre('Punk')), isTrue);
    expect(items.map((item) => item.id).toSet(), hasLength(3));
  });

  test('real HTTPS on first launch, no second download on recreated store',
      () async {
    await HttpOverrides.runWithHttpOverrides(() async {
      final temp = await Directory.systemTemp.createTemp('go-phone-https-lab-');
      try {
        final folder = Directory(temp.path + '/objects');
        CentralLogoAssetStore makeStore() => CentralLogoAssetStore(
          directory: folder,
          decoder: decodeCentralFlutterLogo,
        );
        final first = await prepareHttpsDiagnostic(
          store: makeStore(),
          fetch: const CentralLogoHttpFetcher().fetch,
          buildArtworkIndex: localTestIndex,
        );
        expect(first.networkFetches, 2);
        expect(first.offlineOldFallbackChecked, isTrue);
        expect(first.replayFetches, 0);
        expect(await folder.list().where((entry) =>
            entry.path.endsWith('.img')).length, 2);
        final second = await prepareHttpsDiagnostic(
          store: makeStore(),
          fetch: (uri, bytes) =>
              throw StateError('Already cached SHA must never use HTTP'),
          buildArtworkIndex: localTestIndex,
        );
        expect(second.networkFetches, 0);
        expect(second.offlineOldFallbackChecked, isFalse);
        expect(second.replayFetches, 0);
        for (final descriptor in [
          httpsDiagnosticLogo(1),
          httpsDiagnosticLogo(2),
        ]) {
          expect(await makeStore().findVerified(descriptor), isNotNull);
        }
      } finally {
        if (await temp.exists()) {
          await temp.delete(recursive: true);
        }
      }
    }, _RealNetworkHttpOverrides());
  }, skip: !live);
}
