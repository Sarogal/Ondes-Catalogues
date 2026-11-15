import 'dart:async';
import 'dart:typed_data';

import 'package:test/test.dart';
import 'package:go_radio_catalog_client_lab/central_logo_http_fetcher.dart';
import 'package:go_radio_catalog_client_lab/central_radio_catalog_core.dart';

void main() {
  test('bounded loader accepts only exact signed bytes', () async {
    final image = await readExactCentralLogoBytes(
      Stream<List<int>>.fromIterable(<List<int>>[
        <int>[1, 2],
        <int>[3, 4, 5],
      ]),
      5,
    );
    expect(image, Uint8List.fromList(<int>[1, 2, 3, 4, 5]));
  });

  test('bounded loader rejects overflow before allocation', () async {
    await expectLater(
      readExactCentralLogoBytes(Stream<List<int>>.value(
        <int>[1, 2, 3, 4]), 3),
      throwsA(isA<CentralCatalogException>()),
    );
  });

  test('bounded loader rejects incomplete, empty or impossible sizes', () async {
    await expectLater(
      readExactCentralLogoBytes(
          Stream<List<int>>.value(<int>[1, 2]), 3),
      throwsA(isA<CentralCatalogException>()),
    );
    await expectLater(
      readExactCentralLogoBytes(
          const Stream<List<int>>.empty(), 1),
      throwsA(isA<CentralCatalogException>()),
    );
    await expectLater(
      readExactCentralLogoBytes(
          const Stream<List<int>>.empty(), 0),
      throwsA(isA<CentralCatalogException>()),
    );
  });

  test('logo URL check blocks local, IP, credentials and non-HTTPS', () {
    const bad = <String>[
      'http://example.org/logo.png',
      'https://localhost/logo.png',
      'https://localhost./logo.png',
      'https://radio.local/logo.png',
      'https://radio.internal/logo.png',
      'https://127.0.0.1/logo.png',
      'https://192.168.0.1/logo.png',
      'https://[::1]/logo.png',
      'https://user:pass@example.org/logo.png',
      'https://example.org/logo.png#fragment',
    ];
    for (final candidate in bad) {
      expect(isSafeCentralLogoUrl(Uri.parse(candidate)), isFalse,
          reason: candidate);
    }
    expect(isSafeCentralLogoUrl(Uri.parse(
        'https://grosses-ondes.fr/logos/example.png')), isTrue);
    expect(isSafeCentralLogoUrl(Uri.parse(
        'https://grosses-ondes.fr./logos/example.png')), isTrue);
  });

  test('invalid URLs are rejected before a socket is attempted', () async {
    await expectLater(
      const CentralLogoHttpFetcher().fetch(
        Uri.parse('https://127.0.0.1/private.png'), 200),
      throwsA(isA<CentralCatalogException>()),
    );
    await expectLater(
      const CentralLogoHttpFetcher().fetch(
        Uri.parse('https://example.org/public.png'), 0),
      throwsA(isA<CentralCatalogException>()),
    );
  });
}
