// Pure Dart queue for signed artwork hydration. A disk-only pass and a
// subsequent remote pass must run in order, never silently skip the latter.
// Untrusted images cannot be taken from any job other than the caller's
// authenticated CentralLogoPreparationPlan.
class CentralSignedArtworkWorkQueue {
  Future<void>? _running;

  Future<void> run(Future<void> Function() job) async {
    while (_running != null) {
      try {
        await _running;
      } catch (_) {
        // An earlier IO failure must not starve later signed generations.
      }
    }
    final current = job();
    _running = current;
    try {
      await current;
    } finally {
      if (identical(_running, current)) _running = null;
    }
  }
}
