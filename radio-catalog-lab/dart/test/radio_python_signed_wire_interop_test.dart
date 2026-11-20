import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:go_radio_catalog_client_lab/central_radio_catalog_core.dart';
import 'package:test/test.dart';

/// Integration fixture is generated on the ephemeral GitHub runner by the
/// Python offline-only release packager with a PUBLIC, synthetic test key.
/// No real Grosses Ondes catalogue and no production keys are ever present.
void main() {
  final folder = Platform.environment['GO_RADIO_PY_RELEASE_DIR'];

  test('Python-signed current.json is verified byte-for-byte by the Dart client',
      () async {
    final root = Directory(folder!);
    expect(await root.exists(), isTrue);

    final pointerBytes = Uint8List.fromList(
        await File(root.path + '/current.json').readAsBytes());
    final pointer = CentralCatalogPointer.parse(pointerBytes);
    expect(pointer.sequence, 1);
    expect(pointer.keyId, 'synthetic-ci-key');

    final catalogBytes = Uint8List.fromList(
        await File(root.path + '/' + pointer.path).readAsBytes());
    final publicKeyBytes = base64.decode(
        (await File(root.path + '/synthetic-test-public-key.b64')
                .readAsString()).trim());
    final verifier = CentralCatalogVerifier(
      trustedKeys: {
        'synthetic-ci-key': SimplePublicKey(
          publicKeyBytes, type: KeyPairType.ed25519),
      },
    );

    final accepted = await verifier.verify(
        pointerBytes: pointerBytes, catalogBytes: catalogBytes);
    expect(accepted.stations, hasLength(1));
    expect(accepted.pointer.sequence, 1);
    expect(accepted.aliasOwners['legacy-uuid-001'], 'go-station-000001');
    expect(accepted.activeIds, contains('go-station-000001'));

    final tampered = Uint8List.fromList(catalogBytes);
    tampered[tampered.length - 2] ^= 1;
    await expectLater(
      verifier.verify(pointerBytes: pointerBytes, catalogBytes: tampered),
      throwsA(isA<CentralCatalogException>()),
    );

    final unknownVerifier = CentralCatalogVerifier(trustedKeys: {});
    await expectLater(
      unknownVerifier.verify(
          pointerBytes: pointerBytes, catalogBytes: catalogBytes),
      throwsA(isA<CentralCatalogException>()),
    );
  }, skip: folder == null
      ? 'Synthetic Python-signed fixture is generated only in isolated CI'
      : false);
}
