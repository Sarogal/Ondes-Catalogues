// Isolated V64 logo retry policy. This is NOT the future SHA-based central store.
// Store only the existing local URL-key fingerprint, never a full image URL.
// The policy does not access the network or touch cached image files.
import 'dart:convert';

class LogoRetryBackoff {
  LogoRetryBackoff._(this._records);

  factory LogoRetryBackoff.empty() =>
      LogoRetryBackoff._(<String, _RetryEntry>{});

  factory LogoRetryBackoff.fromJson(String? raw) {
    if (raw == null || raw.trim().isEmpty || raw.length > 128 * 1024) {
      return LogoRetryBackoff.empty();
    }
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return LogoRetryBackoff.empty();
      final records = <String, _RetryEntry>{};
      for (final record in decoded.entries) {
        if (records.length >= 512) break;
        final key = record.key;
        final data = record.value;
        // Dart VM signed 64-bit FNV keys use
        // toRadixString(16).padLeft(16, '0'), allowing leading zeroes
        // before the sign (e.g. "0-22168ddfcfafe0").
        if (key is! String ||
            key.length < 16 ||
            key.length > 17 ||
            !RegExp(r'^(?:[a-f0-9]{16}|0*-[1-9a-f][a-f0-9]{0,15})$')
                .hasMatch(key) ||
            data is! Map) {
          continue;
        }
        final revision = data['revision'];
        final failures = data['failures'];
        final after = data['retry_after_utc'];
        if (revision is! int || revision < 1 ||
            failures is! int || failures < 1 || failures > 4 ||
            after is! String) {
          continue;
        }
        final date = DateTime.tryParse(after);
        if (date == null || !date.isUtc) continue;
        records[key] = _RetryEntry(revision, failures, date);
      }
      return LogoRetryBackoff._(records);
    } catch (_) {
      return LogoRetryBackoff.empty();
    }
  }

  final Map<String, _RetryEntry> _records;

  bool isDeferred({
    required String urlKey,
    required int revision,
    required DateTime now,
  }) {
    final record = _records[urlKey];
    return record != null &&
        record.revision == revision &&
        now.toUtc().isBefore(record.retryAfter);
  }

  /// Failures back off for 6, 12, 24, then 48 hours, surviving app restarts.
  /// New image revisions and new URLs are immediately eligible again.
  void recordFailure({
    required String urlKey,
    required int revision,
    required DateTime now,
  }) {
    if (revision < 1) return;
    final previous = _records[urlKey];
    final failures = previous == null || previous.revision != revision
        ? 1
        : (previous.failures < 4 ? previous.failures + 1 : 4);
    final hours = 6 * (1 << (failures - 1));
    _records[urlKey] = _RetryEntry(
      revision,
      failures,
      now.toUtc().add(Duration(hours: hours)),
    );
    // Bound preference size without recording complete URLs or leaking data.
    if (_records.length > 512) {
      final ordered = _records.entries.toList()
        ..sort((a, b) => a.value.retryAfter.compareTo(b.value.retryAfter));
      for (final entry in ordered.take(_records.length - 512)) {
        _records.remove(entry.key);
      }
    }
  }

  void recordSuccess(String urlKey) => _records.remove(urlKey);

  String toJson() => jsonEncode(<String, Object?>{
        for (final entry in _records.entries)
          entry.key: <String, Object?>{
            'revision': entry.value.revision,
            'failures': entry.value.failures,
            'retry_after_utc': entry.value.retryAfter.toIso8601String(),
          },
      });
}

class _RetryEntry {
  const _RetryEntry(this.revision, this.failures, this.retryAfter);
  final int revision;
  final int failures;
  final DateTime retryAfter;
}
