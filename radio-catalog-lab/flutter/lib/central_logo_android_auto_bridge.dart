// Isolated bridge between permanent SHA assets and Android Auto content://.
// Does not change the V64 URL-keyed cache, existing content URI paths or audio handler.
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'android_auto_artwork_uris.dart';
import 'central_flutter_logo_decoder.dart';
import 'central_logo_asset_store.dart';
import 'central_radio_catalog_core.dart';

class CentralLogoAndroidAutoBridge {
  const CentralLogoAndroidAutoBridge._();

  // Also declared in StationLogoContentProvider.kt. Never reuse the legacy
  // grosses_ondes_station_logos_v2 directory: its maintenance can purge .img.
  static const String directoryName = 'grosses_ondes_central_logos_v1';

  static Future<CentralLogoAssetStore> createStore() async {
    final root = await getApplicationSupportDirectory();
    return CentralLogoAssetStore(
      directory: Directory('${root.path}${Platform.pathSeparator}$directoryName'),
      decoder: decodeCentralFlutterLogo,
    );
  }

  /// Disk-only preflight. The URI is returned only after rechecking the
  /// SHA/bytes/real image decoder in the exact directory served by Kotlin.
  /// No network request, copy, deletion or preference write is performed.
  static Future<Uri?> verifiedArtworkUri({
    required CentralLogoAssetStore store,
    required CentralLogoDescriptor descriptor,
  }) async {
    final root = await getApplicationSupportDirectory();
    final expected = Directory(
      '${root.path}${Platform.pathSeparator}$directoryName',
    ).absolute.path;
    if (store.directory.absolute.path != expected) {
      throw const CentralCatalogException(
        'Central logo store must use the Android Auto content directory',
      );
    }
    if (await store.findVerified(descriptor) == null) return null;
    return AndroidAutoArtworkUris.forCentralSha256(descriptor.sha256);
  }
}
