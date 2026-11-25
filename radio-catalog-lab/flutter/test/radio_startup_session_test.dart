import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/radio_startup_session.dart';

void main() {
  test('one startup serves simultaneous callers and every later read', () async {
    final session = RadioStartupSession<int>();
    final gate = Completer<int?>();
    var calls = 0;
    Future<int?> prepare() {
      calls++;
      return gate.future;
    }
    final ui = session.load(prepare);
    final auto = session.load(prepare);
    gate.complete(8);
    expect(await ui, 8);
    expect(await auto, 8);
    for (var i = 0; i < 285; i++) {
      expect(await session.load(prepare), 8);
    }
    expect(calls, 1);
  });

  test('explicit refresh coalesces but does not block current playback', () async {
    final session = RadioStartupSession<int>();
    await session.load(() async => 8);
    final gate = Completer<int?>();
    final refresh = session.load(() => gate.future, refresh: true);
    final joined = session.load(() => throw StateError('duplicate'), refresh: true);
    expect(await session.load(() => throw StateError('unexpected read')), 8);
    gate.complete(9);
    expect(await refresh, 9);
    expect(await joined, 9);
    expect(session.current, 9);
  });

  test('offline refresh retains the authenticated value', () async {
    final session = RadioStartupSession<int>();
    await session.load(() async => 8);
    expect(await session.load(() async => null, refresh: true), 8);
    expect(await session.load(() => throw StateError('offline'), refresh: true), 8);
  });

  test('first launch failure does not retry on every station lookup', () async {
    final session = RadioStartupSession<int>();
    var calls = 0;
    expect(await session.load(() async { calls++; return null; }), isNull);
    expect(await session.load(() async { calls++; return 8; }), isNull);
    expect(calls, 1);
    expect(await session.load(() async => 8, refresh: true), 8);
  });
}
