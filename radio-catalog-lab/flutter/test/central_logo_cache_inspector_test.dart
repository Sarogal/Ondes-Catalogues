import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_logo_preparation_plan.dart';
import 'package:go_radio_flutter_lab/central_logo_cache_inspector.dart';

Uint8List imageBytes(int seed) => Uint8List.fromList(
      List<int>.generate(128, (i) => (i + seed) & 255),
    );

CentralLogoDescriptor signedLogo(Uint8List data) => CentralLogoDescriptor(
      sha256: crypto.sha256.convert(data).toString(),
      byteSize: data.length,
      revision: 1,
      url: 'https://images.example.org/logo.png',
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

Future<CentralDecodedLogo> fakeImageDecoder(Uint8List data) async =>
    const CentralDecodedLogo(
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

CentralLogoPreparationPlan makePlan(
    List<(CentralLogoDescriptor, List<String>)> items) {
  return CentralLogoPreparationPlan(
    items: [
      for (final item in items)
        CentralLogoPreparationItem(
          descriptor: item.$1,
          stationIds: item.$2,
        ),
    ],
    activeWithoutLogo: const [],
    excludedInactive: const [],
  );
}

void main() {
  late Directory temporary;
  setUp(() async {
    temporary = await Directory.systemTemp.createTemp('go-cache-inspect-');
  });
  tearDown(() async {
    if (await temporary.exists()) {
      await temporary.delete(recursive: true);
    }
  });

  test('missing cache inspection is strictly read-only and offline', () async {
    final directory = Directory('${temporary.path}/not-created');
    final raw = imageBytes(1);
    final descriptor = signedLogo(raw);
    final plan = makePlan([(descriptor, ['go-station-000001'])]);
    final report = await const CentralLogoCacheInspector().inspect(
      plan: plan,
      store: CentralLogoAssetStore(
        directory: directory,
        decoder: fakeImageDecoder,
      ),
    );
    expect(report.missingObjects, 1);
    expect(report.cachedObjects, 0);
    expect(report.missingBytes, raw.length);
    expect(report.cachedStationEntries, 0);
    expect(await directory.exists(), isFalse);
  });

  test('verified local SHA is reused after store recreation', () async {
    final raw = imageBytes(2);
    final descriptor = signedLogo(raw);
    final directory = Directory('${temporary.path}/sha-cache');
    final initialStore = CentralLogoAssetStore(
      directory: directory,
      decoder: fakeImageDecoder,
    );
    var calls = 0;
    final installation = await initialStore.ensure(
      target: descriptor,
      fetch: (url, maxBytes) async {
        calls++;
        return raw;
      },
    );
    expect(installation.status, CentralLogoCacheStatus.downloaded);
    final newStore = CentralLogoAssetStore(
      directory: directory,
      decoder: fakeImageDecoder,
    );
    final plan = makePlan([
      (descriptor, ['go-station-000001', 'go-station-000002']),
    ]);
    final report = await const CentralLogoCacheInspector().inspect(
      plan: plan,
      store: newStore,
    );
    expect(report.cachedObjects, 1);
    expect(report.cachedStationEntries, 2);
    expect(report.missingObjects, 0);
    expect(report.missingBytes, 0);
    expect(report.assets.single.verifiedFile, isNotNull);
    expect(calls, 1); // Only the explicit initial install accessed a fetcher.
    expect(await installation.image!.readAsBytes(), raw);
  });

  test('damaged SHA object is reported missing, not modified', () async {
    final raw = imageBytes(3);
    final broken = imageBytes(4);
    final descriptor = signedLogo(raw);
    final directory = Directory('${temporary.path}/sha-cache');
    final store = CentralLogoAssetStore(
      directory: directory,
      decoder: fakeImageDecoder,
    );
    final installed = await store.ensure(
      target: descriptor,
      fetch: (_, __) async => raw,
    );
    expect(installed.status, CentralLogoCacheStatus.downloaded);
    await installed.image!.writeAsBytes(broken, flush: true);
    final report = await const CentralLogoCacheInspector().inspect(
      plan: makePlan([(descriptor, ['go-station-000001'])]),
      store: store,
    );
    expect(report.cachedObjects, 0);
    expect(report.missingObjects, 1);
    expect(report.missingBytes, raw.length);
    expect(await installed.image!.readAsBytes(), broken);
    final names = await directory
        .list()
        .map((file) => file.uri.pathSegments.last)
        .toList();
    expect(names, hasLength(1)); // No repair, rename or sidecar writes.
  });

  test('counts one missing object for multiple stations and freezes report', () async {
    final one = signedLogo(imageBytes(5));
    final two = signedLogo(imageBytes(6));
    final store = CentralLogoAssetStore(
      directory: Directory('${temporary.path}/cache'),
      decoder: fakeImageDecoder,
    );
    final plan = makePlan([
      (one, ['go-station-000001', 'go-station-000002']),
      (two, ['go-station-000003']),
    ]);
    final report = await const CentralLogoCacheInspector().inspect(
      plan: plan,
      store: store,
    );
    expect(report.missingObjects, 2);
    expect(report.missingBytes, one.byteSize + two.byteSize);
    expect(report.cachedStationEntries, 0);
    expect(() => report.assets.add(report.assets.first),
        throwsUnsupportedError);
  });
}
