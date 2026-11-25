import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/media_selection_intent.dart';

void main() {
  test('a slow old lookup cannot publish over a newer selection', () async {
    final intents = MediaSelectionIntent();
    final slow = Completer<void>();
    final published = <String>[];
    Future<void> select(String id, Future<void> lookup) async {
      final token = intents.begin();
      try {
        await lookup;
        if (!intents.accepts(token)) return;
        intents.finish(token);
        published.add(id);
      } finally {
        intents.finish(token);
      }
    }
    final first = select('A', slow.future);
    await select('B', Future<void>.value());
    slow.complete();
    await first;
    expect(published, ['B']);
    expect(intents.resolving, isFalse);
  });

  test('stale completion cannot release newer unresolved request', () {
    final intents = MediaSelectionIntent();
    final old = intents.begin();
    final next = intents.begin();
    intents.finish(old);
    expect(intents.resolving, isTrue);
    expect(intents.accepts(old), isFalse);
    intents.finish(next);
    expect(intents.resolving, isFalse);
  });

  test('pause or stop invalidates pending resolution and retry token', () {
    final intents = MediaSelectionIntent();
    final retry = intents.current;
    final pending = intents.begin();
    final stop = intents.cancel();
    expect(intents.accepts(retry), isFalse);
    expect(intents.accepts(pending), isFalse);
    expect(intents.accepts(stop), isTrue);
    expect(intents.resolving, isFalse);
  });

  test('disposal rejects every future completion', () {
    final intents = MediaSelectionIntent();
    final pending = intents.begin();
    intents.close();
    expect(intents.accepts(pending), isFalse);
    expect(intents.accepts(intents.begin()), isFalse);
    expect(intents.resolving, isFalse);
  });

  test('the latest explicit intent is reserved before async work', () {
    final intents = MediaSelectionIntent();
    final a = intents.begin();
    final b = intents.begin();
    final c = intents.begin();
    expect(a < b && b < c, isTrue);
    expect(intents.accepts(a), isFalse);
    expect(intents.accepts(b), isFalse);
    expect(intents.accepts(c), isTrue);
  });
}
