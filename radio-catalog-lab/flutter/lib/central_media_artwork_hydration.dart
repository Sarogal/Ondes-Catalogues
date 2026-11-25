import 'dart:async';

/// Coalesces nonblocking disk artwork hydration for authenticated generations.
/// No network, disk or app dependencies. The caller supplies verified work.
class CentralMediaArtworkHydration {
  int? _selectedSequence;
  int? _runningSequence;
  void Function()? _pending;
  bool _closed = false;

  int? get selectedSequence => _selectedSequence;

  void observe(int sequence) {
    if (_closed || sequence <= 0) return;
    if (_selectedSequence == null || sequence > _selectedSequence!) {
      _selectedSequence = sequence;
      _pending = null;
    }
  }

  bool canUse(int? activatedSequence) =>
      !_closed &&
      _selectedSequence != null &&
      _selectedSequence == activatedSequence;

  void schedule({
    required int sequence,
    required bool Function() isPrepared,
    required Future<void> Function() prepare,
    required void Function() onComplete,
  }) {
    observe(sequence);
    if (_closed || sequence != _selectedSequence || isPrepared()) return;
    if (_runningSequence != null) {
      if (sequence > _runningSequence!) {
        _pending = () => schedule(
              sequence: sequence,
              isPrepared: isPrepared,
              prepare: prepare,
              onComplete: onComplete,
            );
      }
      return;
    }
    _runningSequence = sequence;
    unawaited(_run(sequence, prepare, onComplete));
  }

  Future<void> _run(
    int sequence,
    Future<void> Function() prepare,
    void Function() onComplete,
  ) async {
    try {
      await prepare();
    } catch (_) {
      // Optional artwork must not prevent playback. A later read can retry.
    }
    _runningSequence = null;
    if (_closed) return;
    final pending = _pending;
    _pending = null;
    if (sequence == _selectedSequence) {
      try {
        onComplete();
      } catch (_) {
        // A media notification failure must not poison the scheduler.
      }
    }
    pending?.call();
  }

  void close() {
    _closed = true;
    _pending = null;
  }
}
