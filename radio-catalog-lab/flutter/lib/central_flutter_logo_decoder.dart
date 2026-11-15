// Experimental Flutter-only decoder for SHA-verified central logo objects.
// No HTTP, no legacy cache writes, no Android Auto activation.
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'central_logo_asset_store.dart';
import 'central_radio_catalog_core.dart';

/// Checks the actual encoded image with Flutter's engine. The MIME is inferred
/// from magic bytes, not an HTTP Content-Type supplied by an untrusted server.
Future<CentralDecodedLogo> decodeCentralFlutterLogo(Uint8List bytes) async {
  final mimeType = _detectCentralImageMime(bytes);
  if (mimeType == null) {
    throw const CentralCatalogException('Unsupported central logo format');
  }

  ui.Codec? codec;
  ui.Image? image;
  try {
    codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    image = frame.image;
    if (image.width < 1 || image.height < 1 ||
        image.width > 10000 || image.height > 10000) {
      throw const CentralCatalogException('Unsafe decoded logo dimensions');
    }
    return CentralDecodedLogo(
      width: image.width,
      height: image.height,
      mimeType: mimeType,
    );
  } on CentralCatalogException {
    rethrow;
  } catch (_) {
    throw const CentralCatalogException('Flutter could not decode central logo');
  } finally {
    image?.dispose();
    codec?.dispose();
  }
}

String? _detectCentralImageMime(Uint8List bytes) {
  if (bytes.length >= 8 &&
      bytes[0] == 0x89 && bytes[1] == 0x50 &&
      bytes[2] == 0x4e && bytes[3] == 0x47 &&
      bytes[4] == 0x0d && bytes[5] == 0x0a &&
      bytes[6] == 0x1a && bytes[7] == 0x0a) {
    return 'image/png';
  }
  if (bytes.length >= 3 &&
      bytes[0] == 0xff && bytes[1] == 0xd8 && bytes[2] == 0xff) {
    return 'image/jpeg';
  }
  if (bytes.length >= 12 &&
      bytes[0] == 0x52 && bytes[1] == 0x49 &&
      bytes[2] == 0x46 && bytes[3] == 0x46 &&
      bytes[8] == 0x57 && bytes[9] == 0x45 &&
      bytes[10] == 0x42 && bytes[11] == 0x50) {
    return 'image/webp';
  }
  return null;
}
