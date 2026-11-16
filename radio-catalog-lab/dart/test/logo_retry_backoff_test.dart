import 'dart:convert';

import 'package:test/test.dart';
import 'package:go_radio_catalog_client_lab/logo_retry_backoff.dart';

void main() {
  const firstKey = '23264da193e11e2f';
  const signedKey = '-4f03fe91778f6411';
  final start = DateTime.utc(2026, 11, 16, 12);

  test('a failed URL is deferred across process restarts', () {
    final retry = LogoRetryBackoff.empty();
    expect(retry.isDeferred(urlKey: firstKey, revision: 1, now: start),
        isFalse);
    retry.recordFailure(urlKey: firstKey, revision: 1, now: start);
    final newProcess = LogoRetryBackoff.fromJson(retry.toJson());
    expect(newProcess.isDeferred(
        urlKey: firstKey, revision: 1,
        now: start.add(const Duration(hours: 5))), isTrue);
    expect(newProcess.isDeferred(
        urlKey: firstKey, revision: 1,
        now: start.add(const Duration(hours: 6))), isFalse);
  });

  test('repeated failures back off 6, 12, 24, then 48 hours', () {
    final retry = LogoRetryBackoff.empty();
    var at = start;
    for (final hours in [6, 12, 24, 48, 48]) {
      retry.recordFailure(urlKey: firstKey, revision: 1, now: at);
      expect(retry.isDeferred(
          urlKey: firstKey, revision: 1,
          now: at.add(Duration(hours: hours - 1))), isTrue);
      at = at.add(Duration(hours: hours));
      expect(retry.isDeferred(
          urlKey: firstKey, revision: 1, now: at), isFalse);
    }
  });

  test('new revision and new URL bypass existing deferral', () {
    final retry = LogoRetryBackoff.empty();
    retry.recordFailure(urlKey: firstKey, revision: 1, now: start);
    expect(retry.isDeferred(
        urlKey: firstKey, revision: 2, now: start), isFalse);
    expect(retry.isDeferred(
        urlKey: signedKey, revision: 1, now: start), isFalse);
    retry.recordFailure(urlKey: firstKey, revision: 2, now: start);
    expect(retry.isDeferred(
        urlKey: firstKey, revision: 2,
        now: start.add(const Duration(hours: 5))), isTrue);
  });

  test('success clears retries and keeps negative signed keys', () {
    final retry = LogoRetryBackoff.empty();
    retry.recordFailure(urlKey: signedKey, revision: 1, now: start);
    final stored = retry.toJson();
    expect(stored, contains(signedKey));
    expect(stored, isNot(contains('https://')));
    final restarted = LogoRetryBackoff.fromJson(stored);
    expect(restarted.isDeferred(
        urlKey: signedKey, revision: 1, now: start), isTrue);
    restarted.recordSuccess(signedKey);
    expect(restarted.isDeferred(
        urlKey: signedKey, revision: 1, now: start), isFalse);
  });

  test('zero-padded negative signed FNV key is restored after restart', () {
    // Existing Android Dart VM key from a radcap image with a small
    // negative magnitude: padLeft places zeroes *before* the minus sign.
    const key = '0-22168ddfcfafe0';
    final retry = LogoRetryBackoff.empty();
    retry.recordFailure(urlKey: key, revision: 1, now: start);

    final stored = retry.toJson();
    final restarted = LogoRetryBackoff.fromJson(stored);
    expect(stored, contains(key));
    expect(
      restarted.isDeferred(
        urlKey: key,
        revision: 1,
        now: start.add(const Duration(minutes: 5)),
      ),
      isTrue,
    );
    expect(
      restarted.isDeferred(
        urlKey: key,
        revision: 2,
        now: start.add(const Duration(minutes: 5)),
      ),
      isFalse,
    );
  });

  test('invalid or excessive preference content is safely ignored', () {
    expect(LogoRetryBackoff.fromJson('{').toJson(), '{}');
    expect(LogoRetryBackoff.fromJson('[]').toJson(), '{}');
    expect(LogoRetryBackoff.fromJson('x' * 131073).toJson(), '{}');
    final corrupt = jsonEncode({
      'https://secret.example/logo.png': {
        'revision': 1,
        'failures': 1,
        'retry_after_utc': start.toIso8601String(),
      },
      firstKey: {
        'revision': 0,
        'failures': 100,
        'retry_after_utc': 'invalid',
      },
    });
    expect(LogoRetryBackoff.fromJson(corrupt).toJson(), '{}');
  });

  test('the retry record never includes a downloaded image or URL', () {
    final retry = LogoRetryBackoff.empty();
    retry.recordFailure(urlKey: signedKey, revision: 4, now: start);
    final serialized = retry.toJson();
    expect(serialized, contains('retry_after_utc'));
    expect(serialized, isNot(contains('radcap.ru')));
    expect(serialized, isNot(contains('stylegraf')));
  });
}
