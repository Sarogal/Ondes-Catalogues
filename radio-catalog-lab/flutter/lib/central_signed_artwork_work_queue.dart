// Pure Dart FIFO queue for signed artwork hydration. Disk-only, network,
// Android Auto and UI passes must never overlap or silently drop each other.
// A failed job propagates to its caller without poisoning later jobs.
class CentralSignedArtworkWorkQueue {
  Future<void> _tail = Future<void>.value();

  Future<void> run(Future<void> Function() job) {
    // Reserve the next slot synchronously, before any await. Waiting on a
    // shared in-flight Future with a while-loop is unsafe: multiple waiters
    // can wake together and start their jobs concurrently.
    final current = _tail.then((_) => job());
    // Swallow failure ONLY in the internal scheduling tail. The returned
    // future retains the original error for the job's caller.
    _tail = current.then<void>((_) {}, onError: (Object _, StackTrace __) {});
    return current;
  }
}
