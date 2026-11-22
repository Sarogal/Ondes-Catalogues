import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_signed_artwork_work_queue.dart';

void main() {
  test('online SHA pass is queued, never dropped during signed disk hydration', () async {
    final queue = CentralSignedArtworkWorkQueue();
    final holdDisk = Completer<void>();
    final events = <String>[];
    final disk = queue.run(() async {
      events.add('offline-begins');
      await holdDisk.future;
      events.add('offline-finishes');
    });
    final online = queue.run(() async {
      events.add('network-begins');
      await Future<void>.value();
      events.add('network-finishes');
    });
    await Future<void>.delayed(Duration.zero);
    expect(events, ['offline-begins']);
    holdDisk.complete();
    await Future.wait([disk, online]);
    expect(events, [
      'offline-begins', 'offline-finishes',
      'network-begins', 'network-finishes',
    ]);
  });

  test('rejected disk pass does not starve a later signed network generation', () async {
    final queue = CentralSignedArtworkWorkQueue();
    final events = <String>[];
    final failed = queue.run(() async {
      events.add('broken-disk');
      throw StateError('Corrupt signed cache');
    });
    final failingAssertion = expectLater(failed, throwsStateError);
    final network = queue.run(() async {
      events.add('valid-remote');
    });
    await failingAssertion;
    await network;
    expect(events, ['broken-disk', 'valid-remote']);
  });

  test('uncontended future passes still run after completed queue', () async {
    final queue = CentralSignedArtworkWorkQueue();
    var count = 0;
    await queue.run(() async { count++; });
    await queue.run(() async { count++; });
    expect(count, 2);
  });
}
