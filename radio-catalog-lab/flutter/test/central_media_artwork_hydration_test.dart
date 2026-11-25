import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_media_artwork_hydration.dart';

Future<void> tick() => Future<void>.delayed(Duration.zero);

void main() {
  test('selection returns while artwork is pending, duplicate reads coalesce', () async {
    final hydration = CentralMediaArtworkHydration();
    final hold = Completer<void>();
    var started = 0;
    var completed = 0;
    int? activated;
    void schedule() => hydration.schedule(
      sequence: 8,
      isPrepared: () => activated == 8,
      prepare: () async {
        started++;
        await hold.future;
        activated = 8;
      },
      onComplete: () => completed++,
    );
    schedule();
    schedule();
    expect(hydration.selectedSequence, 8);
    expect(hydration.canUse(activated), isFalse);
    expect(started, 1);
    expect(completed, 0);
    hold.complete();
    await tick();
    expect(hydration.canUse(activated), isTrue);
    expect(completed, 1);
    schedule();
    expect(started, 1);
  });

  test('only the newest pending generation hydrates after an older job', () async {
    final hydration = CentralMediaArtworkHydration();
    final hold = Completer<void>();
    final events = <String>[];
    int? activated;
    void schedule(int sequence) => hydration.schedule(
      sequence: sequence,
      isPrepared: () => activated == sequence,
      prepare: () async {
        events.add('start-$sequence');
        if (sequence == 8) await hold.future;
        activated = sequence;
      },
      onComplete: () => events.add('complete-$sequence'),
    );
    schedule(8);
    schedule(9);
    schedule(10);
    schedule(9);
    expect(hydration.selectedSequence, 10);
    expect(hydration.canUse(8), isFalse);
    hold.complete();
    await tick();
    expect(events, ['start-8', 'start-10', 'complete-10']);
    expect(hydration.canUse(10), isTrue);
    expect(hydration.canUse(9), isFalse);
  });

  test('a newer remote observation invalidates an older pending request', () async {
    final hydration = CentralMediaArtworkHydration();
    final hold = Completer<void>();
    final events = <int>[];
    void schedule(int sequence) => hydration.schedule(
      sequence: sequence,
      isPrepared: () => false,
      prepare: () async {
        events.add(sequence);
        if (sequence == 8) await hold.future;
      },
      onComplete: () => events.add(-sequence),
    );
    schedule(8);
    schedule(9);
    hydration.observe(10);
    hold.complete();
    await tick();
    expect(events, [8]);
    expect(hydration.canUse(8), isFalse);
    expect(hydration.canUse(10), isTrue);
  });

  test('failed hydration allows later retry without authorizing artwork', () async {
    final hydration = CentralMediaArtworkHydration();
    var attempts = 0;
    int? activated;
    void schedule() => hydration.schedule(
      sequence: 8,
      isPrepared: () => activated == 8,
      prepare: () async {
        if (++attempts == 1) throw StateError('unavailable');
        activated = 8;
      },
      onComplete: () {},
    );
    schedule();
    await tick();
    expect(hydration.canUse(activated), isFalse);
    schedule();
    await tick();
    expect(attempts, 2);
    expect(hydration.canUse(activated), isTrue);
  });

  test('disposal suppresses callbacks and queued work', () async {
    final hydration = CentralMediaArtworkHydration();
    final hold = Completer<void>();
    final events = <int>[];
    void schedule(int sequence) => hydration.schedule(
      sequence: sequence,
      isPrepared: () => false,
      prepare: () async {
        events.add(sequence);
        await hold.future;
      },
      onComplete: () => events.add(-sequence),
    );
    schedule(8);
    schedule(9);
    hydration.close();
    hold.complete();
    await tick();
    schedule(10);
    expect(events, [8]);
    expect(hydration.canUse(9), isFalse);
  });
}
