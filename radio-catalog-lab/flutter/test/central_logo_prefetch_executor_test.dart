import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_logo_preparation_plan.dart';
import 'package:go_radio_flutter_lab/central_logo_prefetch_executor.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

Uint8List sampleImage(int seed) => Uint8List.fromList(
      List<int>.generate(128, (index) => (index + seed) & 255),
    );

CentralLogoDescriptor imageSpec(
  Uint8List bytes, {
  String url = 'https://images.example.org/radio.png',
}) =>
    CentralLogoDescriptor(
      sha256: crypto.sha256.convert(bytes).toString(),
      byteSize: bytes.length,
      revision: 1,
      url: url,
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

Future<CentralDecodedLogo> fakeDecoder(Uint8List ignored) async =>
    const CentralDecodedLogo(
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

CentralLogoPreparationPlan plan(
  List<(CentralLogoDescriptor, List<String>)> descriptors,
) =>
    CentralLogoPreparationPlan(
      items: [
        for (final entry in descriptors)
          CentralLogoPreparationItem(
            descriptor: entry.$1,
            stationIds: entry.$2,
          ),
      ],
      activeWithoutLogo: const [],
      excludedInactive: const [],
    );

CentralLogoPrefetchPolicy approved({
  int maxObjects = 12,
  int maxBytes = 8 * 1024 * 1024,
  Set<String> hosts = const {'images.example.org'},
}) =>
    CentralLogoPrefetchPolicy(
      allowNetwork: true,
      allowedHosts: hosts,
      maxObjects: maxObjects,
      maxBytes: maxBytes,
    );

void main() {
  late Directory temp;
  setUp(() async {
    temp = await Directory.systemTemp.createTemp('go-logo-prefetch-');
  });
  tearDown(() async {
    if (await temp.exists()) await temp.delete(recursive: true);
  });

  test('default offline never invokes supplied fetcher or creates cache', () async {
    final image = sampleImage(1);
    final directory = Directory('${temp.path}/not-created');
    var calls = 0;
    final report = await CentralLogoPrefetchExecutor().execute(
      plan: plan([(imageSpec(image), ['go-station-000001'])]),
      store: CentralLogoAssetStore(
        directory: directory,
        decoder: fakeDecoder,
      ),
      fetch: (uri, maxBytes) async {
        calls++;
        return image;
      },
    );
    expect(report.entries.single.outcome, CentralLogoPrefetchOutcome.offline);
    expect(report.reservedAttempts, 0);
    expect(report.reservedBytes, 0);
    expect(calls, 0);
    expect(await directory.exists(), isFalse);
  });

  test('network requires both approved hostname and explicit fetcher', () async {
    expect(
      () => CentralLogoPrefetchPolicy(
        allowNetwork: true,
        allowedHosts: const <String>{},
      ),
      throwsA(isA<CentralCatalogException>()),
    );
    expect(
      () => CentralLogoPrefetchPolicy(
        allowNetwork: true,
        allowedHosts: const {'localhost'},
      ),
      throwsA(isA<CentralCatalogException>()),
    );
    final image = sampleImage(2);
    final store = CentralLogoAssetStore(
      directory: Directory('${temp.path}/cache'),
      decoder: fakeDecoder,
    );
    await expectLater(
      CentralLogoPrefetchExecutor().execute(
        plan: plan([(imageSpec(image), ['go-station-000001'])]),
        store: store,
        policy: approved(),
      ),
      throwsA(isA<CentralCatalogException>()),
    );
    expect(await store.directory.exists(), isFalse);
  });

  test('one approved download serves multiple radios across restarts', () async {
    final image = sampleImage(3);
    final descriptor = imageSpec(image);
    final directory = Directory('${temp.path}/cache');
    final signedPlan = plan([
      (descriptor, ['go-station-000001', 'go-station-000002']),
    ]);
    var calls = 0;
    Future<Uint8List> fetch(Uri _, int __) async {
      calls++;
      return image;
    }

    final initial = await CentralLogoPrefetchExecutor().execute(
      plan: signedPlan,
      store: CentralLogoAssetStore(
        directory: directory,
        decoder: fakeDecoder,
      ),
      policy: approved(),
      fetch: fetch,
    );
    expect(initial.downloadedObjects, 1);
    expect(initial.reservedAttempts, 1);
    expect(initial.reservedBytes, image.length);
    expect(initial.entries.single.planned.stationIds.length, 2);

    final afterRestart = await CentralLogoPrefetchExecutor().execute(
      plan: signedPlan,
      store: CentralLogoAssetStore(
        directory: directory,
        decoder: fakeDecoder,
      ),
      policy: approved(),
      fetch: fetch,
    );
    expect(afterRestart.cachedObjects, 1);
    expect(afterRestart.reservedAttempts, 0);
    expect(calls, 1);
  });

  test('strict host allowlist and budgets prevent unwanted requests', () async {
    final first = sampleImage(4);
    final second = sampleImage(5);
    final third = sampleImage(6);
    var calls = 0;
    final report = await CentralLogoPrefetchExecutor().execute(
      plan: plan([
        (imageSpec(first, url: 'https://unapproved.example.net/logo.png'),
            ['go-station-000001']),
        (imageSpec(second), ['go-station-000002']),
        (imageSpec(third), ['go-station-000003']),
      ]),
      store: CentralLogoAssetStore(
        directory: Directory('${temp.path}/cache'),
        decoder: fakeDecoder,
      ),
      policy: approved(maxObjects: 1, maxBytes: 128),
      fetch: (uri, maxBytes) async {
        calls++;
        return second;
      },
    );
    expect(
      report.entries.map((entry) => entry.outcome).toList(),
      [
        CentralLogoPrefetchOutcome.hostBlocked,
        CentralLogoPrefetchOutcome.downloaded,
        CentralLogoPrefetchOutcome.budgetExceeded,
      ],
    );
    expect(calls, 1);
    expect(report.reservedAttempts, 1);
    expect(report.reservedBytes, 128);
  });

  test('bad SHA retains retry cooldown and does not re-fetch next boot', () async {
    final good = sampleImage(7);
    final bad = sampleImage(8);
    final descriptor = imageSpec(good);
    final directory = Directory('${temp.path}/cache');
    var fetchCalls = 0;
    final first = await CentralLogoPrefetchExecutor().execute(
      plan: plan([(descriptor, ['go-station-000001'])]),
      store: CentralLogoAssetStore(
        directory: directory,
        decoder: fakeDecoder,
      ),
      policy: approved(),
      fetch: (uri, maxBytes) async {
        fetchCalls++;
        return bad;
      },
    );
    expect(first.entries.single.outcome, CentralLogoPrefetchOutcome.rejected);
    final second = await CentralLogoPrefetchExecutor().execute(
      plan: plan([(descriptor, ['go-station-000001'])]),
      store: CentralLogoAssetStore(
        directory: directory,
        decoder: fakeDecoder,
      ),
      policy: approved(),
      fetch: (uri, maxBytes) async {
        fetchCalls++;
        return good;
      },
    );
    expect(
      second.entries.single.outcome,
      CentralLogoPrefetchOutcome.retryDeferred,
    );
    expect(fetchCalls, 1);
  });

  test('duplicate SHA in malformed plan is rejected before repeated fetch', () async {
    final image = sampleImage(9);
    final descriptor = imageSpec(image);
    var calls = 0;
    await expectLater(
      CentralLogoPrefetchExecutor().execute(
        plan: plan([
          (descriptor, ['go-station-000001']),
          (descriptor, ['go-station-000002']),
        ]),
        store: CentralLogoAssetStore(
          directory: Directory('${temp.path}/cache'),
          decoder: fakeDecoder,
        ),
        policy: approved(),
        fetch: (uri, maxBytes) async {
          calls++;
          return image;
        },
      ),
      throwsA(isA<CentralCatalogException>()),
    );
    // A malformed plan must fail before any network or cache write.
    expect(calls, 0);
  });

  test('bounded parallel downloads, stable report order and warm cache', () async {
    final images = List.generate(9, (i) => sampleImage(30 + i));
    final signed = plan([
      for (var i = 0; i < images.length; i++)
        (imageSpec(images[i], url: 'https://images.example.org/$i.png'), ['station-$i']),
    ]);
    final directory = Directory('${temp.path}/parallel');
    final firstBatch = Completer<void>();
    var active = 0;
    var peak = 0;
    var calls = 0;
    Future<Uint8List> fetch(Uri uri, int maxBytes) async {
      calls++;
      active++;
      if (active > peak) peak = active;
      if (calls == 3) firstBatch.complete();
      await firstBatch.future.timeout(const Duration(seconds: 5));
      await Future<void>.delayed(const Duration(milliseconds: 5));
      active--;
      return images[int.parse(uri.pathSegments.last.split('.').first)];
    }
    final policy = CentralLogoPrefetchPolicy(
      allowNetwork: true, allowedHosts: const {'images.example.org'},
      maxConcurrent: 3, maxObjects: 9, maxBytes: 9 * 128,
    );
    Future<CentralLogoPrefetchReport> run() =>
      CentralLogoPrefetchExecutor().execute(
        plan: signed, store: CentralLogoAssetStore(directory: directory, decoder: fakeDecoder),
        policy: policy, fetch: fetch,
      );
    final cold = await run();
    expect(peak, 3);
    expect(cold.downloadedObjects, 9);
    expect(cold.reservedAttempts, 9);
    expect(cold.entries.map((e) => e.planned.descriptor.sha256),
      signed.items.map((e) => e.descriptor.sha256));
    final warm = await run();
    expect(warm.cachedObjects, 9);
    expect(warm.reservedAttempts, 0);
    expect(calls, 9);
  });

  test('parallel transfers cannot oversubscribe attempt or byte quotas', () async {
    final images = List.generate(8, (i) => sampleImage(60 + i));
    var calls = 0;
    final report = await CentralLogoPrefetchExecutor().execute(
      plan: plan([
        for (var i = 0; i < images.length; i++)
          (imageSpec(images[i], url: 'https://images.example.org/$i.png'), ['station-$i']),
      ]),
      store: CentralLogoAssetStore(directory: temp, decoder: fakeDecoder),
      policy: CentralLogoPrefetchPolicy(
        allowNetwork: true, allowedHosts: const {'images.example.org'},
        maxConcurrent: 4, maxObjects: 3, maxBytes: 2 * 128,
      ),
      fetch: (uri, size) async {
        calls++;
        return images[int.parse(uri.pathSegments.last.split('.').first)];
      },
    );
    expect(calls, 2);
    expect(report.reservedAttempts, 2);
    expect(report.reservedBytes, 256);
    expect(report.downloadedObjects, 2);
    expect(report.entries.where((e) => e.outcome == CentralLogoPrefetchOutcome.budgetExceeded).length, 6);
  });

  test('zero admission window still verifies cached objects', () async {
    final bytes = sampleImage(100);
    final descriptor = imageSpec(bytes);
    final store = CentralLogoAssetStore(directory: temp, decoder: fakeDecoder);
    await store.ensure(target: descriptor, fetch: (_, __) async => bytes);
    final report = await CentralLogoPrefetchExecutor().execute(
      plan: plan([(descriptor, ['cached']), (imageSpec(sampleImage(101)), ['missing'])]),
      store: store,
      policy: CentralLogoPrefetchPolicy(
        allowNetwork: true, allowedHosts: const {'images.example.org'},
        maxConcurrent: 2, maxNetworkDuration: Duration.zero,
      ),
      fetch: (_, __) async => throw StateError('network must not be admitted'),
    );
    expect(report.cachedObjects, 1);
    expect(report.entries.last.outcome, CentralLogoPrefetchOutcome.budgetExceeded);
    expect(report.reservedAttempts, 0);
  });

}
