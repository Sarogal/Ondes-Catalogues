import 'dart:io';
import 'dart:typed_data';
import 'package:crypto/crypto.dart' as crypto;
import 'package:go_radio_catalog_client_lab/central_logo_asset_store.dart';
import 'package:go_radio_catalog_client_lab/central_radio_catalog_core.dart';
import 'package:test/test.dart';

Uint8List bytes(int seed) => Uint8List.fromList(
  List<int>.generate(64, (index) => (seed + index) & 0xff),
);
CentralLogoDescriptor spec(Uint8List image, {int revision = 1}) =>
    CentralLogoDescriptor(
      sha256: crypto.sha256.convert(image).toString(),
      byteSize: image.length,
      revision: revision,
      url: 'https://example.org/image-$revision.png',
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

Future<CentralDecodedLogo> decode(Uint8List _) async =>
    const CentralDecodedLogo(width: 512, height: 512, mimeType: 'image/png');

void main() {
  late Directory temp;
  setUp(() async {
    temp = await Directory.systemTemp.createTemp('go-immutable-logo-');
  });
  tearDown(() async {
    if (await temp.exists()) await temp.delete(recursive: true);
  });

  test('one SHA is downloaded once and reused across simulated restarts',
      () async {
    final image = bytes(1);
    final descriptor = spec(image);
    var fetchCalls = 0;
    Future<Uint8List> fetch(Uri _, int _) async {
      fetchCalls++;
      return image;
    }
    final first = CentralLogoAssetStore(directory: temp, decoder: decode);
    final installed = await first.ensure(target: descriptor, fetch: fetch);
    expect(installed.status, CentralLogoCacheStatus.downloaded);
    expect(installed.image, isNotNull);
    expect(await installed.image!.readAsBytes(), image);
    final nextBoot = CentralLogoAssetStore(directory: temp, decoder: decode);
    final second = await nextBoot.ensure(target: descriptor, fetch: fetch);
    expect(second.status, CentralLogoCacheStatus.cacheHit);
    expect(fetchCalls, 1);
  });

  test('offline with no asset does not initiate network activity', () async {
    final result = await CentralLogoAssetStore(directory: temp, decoder: decode)
        .ensure(target: spec(bytes(2)));
    expect(result.status, CentralLogoCacheStatus.offline);
    expect(result.image, isNull);
    expect(await temp.exists(), isTrue);
  });

  test('new revision never removes previous valid SHA file', () async {
    final old = bytes(3);
    final newer = bytes(4);
    final oldSpec = spec(old, revision: 1);
    final newSpec = spec(newer, revision: 2);
    final cache = CentralLogoAssetStore(directory: temp, decoder: decode);
    final oldResult = await cache.ensure(target: oldSpec, fetch: (u,m) async => old);
    final oldPath = oldResult.image!.path;
    final latest = await cache.ensure(
      target: newSpec, previous: oldSpec, fetch: (u,m) async => newer);
    expect(latest.status, CentralLogoCacheStatus.downloaded);
    expect(latest.usedOlderLogo, isFalse);
    expect(await File(oldPath).exists(), isTrue);
    expect(await File(oldPath).readAsBytes(), old);
    expect(await latest.image!.readAsBytes(), newer);
  });

  test('bad new SHA retains previous verified logo and cools down across boots',
      () async {
    final old = bytes(5);
    final expected = bytes(6);
    final previous = spec(old, revision: 1);
    final next = spec(expected, revision: 2);
    var now = DateTime.utc(2026, 11, 15, 20);
    var fetchCount = 0;
    Future<Uint8List> badFetch(Uri _, int __) async {
      fetchCount++;
      return bytes(7);
    }
    final first = CentralLogoAssetStore(
        directory: temp, decoder: decode, clock: () => now);
    await first.ensure(target: previous, fetch: (u,m) async => old);
    final rejected = await first.ensure(
        target: next, previous: previous, fetch: badFetch);
    expect(rejected.status, CentralLogoCacheStatus.downloadRejected);
    expect(rejected.usedOlderLogo, isTrue);
    expect(rejected.image, isNotNull);
    expect(await rejected.image!.readAsBytes(), old);
    final nextBoot = CentralLogoAssetStore(
        directory: temp, decoder: decode, clock: () => now);
    final deferred = await nextBoot.ensure(
        target: next, previous: previous, fetch: badFetch);
    expect(deferred.status, CentralLogoCacheStatus.retryDeferred);
    expect(deferred.usedOlderLogo, isTrue);
    expect(fetchCount, 1);
    now = now.add(const Duration(hours: 7));
    final retry = await nextBoot.ensure(
        target: next, previous: previous, fetch: badFetch);
    expect(retry.status, CentralLogoCacheStatus.downloadRejected);
    expect(fetchCount, 2);
  });

  test('invalid decoded dimensions never activate a newly downloaded logo',
      () async {
    final image = bytes(8);
    final cache = CentralLogoAssetStore(
      directory: temp,
      decoder: (raw) async =>
        const CentralDecodedLogo(
          width: 128, height: 512, mimeType: 'image/png'),
    );
    final result = await cache.ensure(
        target: spec(image), fetch: (u,m) async => image);
    expect(result.status, CentralLogoCacheStatus.downloadRejected);
    expect(result.image, isNull);
  });

  test('corrupt disk image is preserved separately then repaired by trusted bytes',
      () async {
    final image = bytes(9);
    final descriptor = spec(image);
    final cache = CentralLogoAssetStore(directory: temp, decoder: decode);
    final first = await cache.ensure(
        target: descriptor, fetch: (u,m) async => image);
    final original = first.image!;
    await original.writeAsBytes(bytes(10), flush: true);
    expect(await cache.findVerified(descriptor), isNull);
    final repaired = await cache.ensure(
        target: descriptor, fetch: (u,m) async => image);
    expect(repaired.status, CentralLogoCacheStatus.downloaded);
    expect(await repaired.image!.readAsBytes(), image);
    final names = await temp.list().map((f) => f.uri.pathSegments.last).toList();
    expect(names.where((name) => name.contains('.invalid.')), hasLength(1));
  });

  test('parallel same-SHA requests share a single explicit fetch', () async {
    final image = bytes(11);
    final descriptor = spec(image);
    final cache = CentralLogoAssetStore(directory: temp, decoder: decode);
    var fetchCount = 0;
    Future<Uint8List> fetch(Uri _, int __) async {
      fetchCount++;
      await Future<void>.delayed(const Duration(milliseconds: 30));
      return image;
    }
    final replies = await Future.wait([
      cache.ensure(target: descriptor, fetch: fetch),
      cache.ensure(target: descriptor, fetch: fetch),
      cache.ensure(target: descriptor, fetch: fetch),
    ]);
    expect(fetchCount, 1);
    expect(replies.every((r) => r.available), isTrue);
    expect(replies.every((r) => r.status == CentralLogoCacheStatus.downloaded), isTrue);
  });

  test('two different stations sharing SHA use one physical immutable object',
      () async {
    final image = bytes(12);
    final descriptor = spec(image);
    final cache = CentralLogoAssetStore(directory: temp, decoder: decode);
    var fetchCount = 0;
    Future<Uint8List> fetch(Uri _, int __) async {
      fetchCount++;
      return image;
    }
    await cache.ensure(target: descriptor, fetch: fetch);
    final second = await cache.ensure(target: spec(image,revision: 5), fetch: fetch);
    expect(second.status, CentralLogoCacheStatus.cacheHit);
    expect(fetchCount, 1);
    final images = await temp.list()
        .where((e) => e.uri.pathSegments.last.endsWith('.img')).toList();
    expect(images, hasLength(1));
  });

  test('unsafe URL, invalid hash and dimensions are refused at construction',
      () async {
    final good = spec(bytes(13));
    expect(
      () => CentralLogoDescriptor(
        sha256: good.sha256, byteSize: good.byteSize, revision: 1,
        url: 'http://localhost/logo.png', width: 512, height: 512,
        mimeType: 'image/png'),
      throwsA(isA<CentralCatalogException>()),
    );
    expect(
      () => CentralLogoDescriptor(
        sha256: 'abc', byteSize: good.byteSize, revision: 1,
        url: good.url, width: 512, height: 512,
        mimeType: 'image/png'),
      throwsA(isA<CentralCatalogException>()),
    );
    expect(
      () => CentralLogoDescriptor(
        sha256: good.sha256, byteSize: good.byteSize, revision: 1,
        url: good.url, width: 0, height: 512,
        mimeType: 'image/png'),
      throwsA(isA<CentralCatalogException>()),
    );
  });

  test('signed catalog station without a logo makes no asset request',
      () async {
    expect(CentralLogoDescriptor.fromSignedStation(
      {'go_station_id':'go-station-000001','logo':null}), isNull);
  });
}
