import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:crypto/crypto.dart' as crypto;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_flutter_logo_decoder.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

Future<Uint8List> _realPng() async {
  final recorder = ui.PictureRecorder();
  final canvas = ui.Canvas(recorder);
  canvas.drawRect(
    const ui.Rect.fromLTWH(0, 0, 3, 4),
    ui.Paint()..color = const ui.Color(0xff123456),
  );
  final picture = recorder.endRecording();
  final image = await picture.toImage(3, 4);
  try {
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    return data!.buffer.asUint8List();
  } finally {
    image.dispose();
    picture.dispose();
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Flutter engine decodes a genuine PNG and returns native dimensions', () async {
    final raw = await _realPng();
    final decoded = await decodeCentralFlutterLogo(raw);
    expect(decoded.mimeType, 'image/png');
    expect(decoded.width, 3);
    expect(decoded.height, 4);
  });

  test('rejects unsupported and truncated encodings', () async {
    await expectLater(
      decodeCentralFlutterLogo(Uint8List.fromList([1, 2, 3, 4])),
      throwsA(isA<CentralCatalogException>()),
    );
    await expectLater(
      decodeCentralFlutterLogo(Uint8List.fromList([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
      ])),
      throwsA(isA<CentralCatalogException>()),
    );
  });

  test('real Flutter decoding rejects false MIME without installing a file', () async {
    final raw = await _realPng();
    final temp = await Directory.systemTemp.createTemp('go-flutter-codec-');
    try {
      final descriptor = CentralLogoDescriptor(
        sha256: crypto.sha256.convert(raw).toString(),
        byteSize: raw.length,
        revision: 1,
        url: 'https://example.org/logo.jpg',
        width: 3,
        height: 4,
        mimeType: 'image/jpeg', // bytes genuinely encode PNG
      );
      final store = CentralLogoAssetStore(
        directory: temp,
        decoder: decodeCentralFlutterLogo,
      );
      final result = await store.ensure(
        target: descriptor,
        fetch: (uri, size) async => raw,
      );
      expect(result.status, CentralLogoCacheStatus.downloadRejected);
      expect(result.image, isNull);
      expect(await store.findVerified(descriptor), isNull);
    } finally {
      await temp.delete(recursive: true);
    }
  });

  test('one genuine SHA logo survives a new store with zero network calls', () async {
    final raw = await _realPng();
    final temp = await Directory.systemTemp.createTemp('go-flutter-reboot-');
    try {
      final descriptor = CentralLogoDescriptor(
        sha256: crypto.sha256.convert(raw).toString(),
        byteSize: raw.length,
        revision: 1,
        url: 'https://example.org/logo.png',
        width: 3,
        height: 4,
        mimeType: 'image/png',
      );
      var requests = 0;
      Future<Uint8List> fetch(Uri uri, int max) async {
        requests++;
        return raw;
      }
      final first = CentralLogoAssetStore(directory: temp, decoder: decodeCentralFlutterLogo);
      final initial = await first.ensure(target: descriptor, fetch: fetch);
      expect(initial.status, CentralLogoCacheStatus.downloaded);
      final second = CentralLogoAssetStore(directory: temp, decoder: decodeCentralFlutterLogo);
      final result = await second.ensure(target: descriptor, fetch: fetch);
      expect(result.status, CentralLogoCacheStatus.cacheHit);
      expect(requests, 1);
    } finally {
      await temp.delete(recursive: true);
    }
  });
}
