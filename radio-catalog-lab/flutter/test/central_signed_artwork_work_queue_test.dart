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

  test('three waiting logo passes never overlap and run in FIFO order', () async {
    final queue = CentralSignedArtworkWorkQueue();
    final holds = List.generate(3, (_) => Completer<void>());
    final events = <String>[];
    var active = 0;
    var maximumActive = 0;

    final tasks = List.generate(3, (index) => queue.run(() async {
      active++;
      if (active > maximumActive) maximumActive = active;
      events.add('start-$index');
      await holds[index].future;
      events.add('end-$index');
      active--;
    }));

    await Future<void>.delayed(Duration.zero);
    expect(events, ['start-0']);
    holds[0].complete();
    await Future<void>.delayed(Duration.zero);
    expect(events, ['start-0', 'end-0', 'start-1']);
    holds[1].complete();
    await Future<void>.delayed(Duration.zero);
    expect(events, ['start-0', 'end-0', 'start-1', 'end-1', 'start-2']);
    holds[2].complete();
    await Future.wait(tasks);
    expect(maximumActive, 1);
    expect(events, [
      'start-0', 'end-0',
      'start-1', 'end-1',
      'start-2', 'end-2',
    ]);
  });

  test('uncontended future passes still run after completed queue', () async {
    final queue = CentralSignedArtworkWorkQueue();
    var count = 0;
    await queue.run(() async { count++; });
    await queue.run(() async { count++; });
    expect(count, 2);
  });
}
