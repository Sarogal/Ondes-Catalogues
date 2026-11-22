/// Keeps verified SHA artwork generations monotonic across overlapping
/// Android Auto and Flutter UI requests. No disk/network dependencies.
class CentralSignedArtworkVersionGuard {
  int? _activatedSequence;

  int? get activatedSequence => _activatedSequence;

  bool permits(int signedSequence) =>
      signedSequence > 0 &&
      (_activatedSequence == null || signedSequence >= _activatedSequence!);

  void markActivated(int signedSequence) {
    if (!permits(signedSequence)) {
      throw StateError('Older signed artwork cannot replace a newer generation');
    }
    _activatedSequence = signedSequence;
  }

  void reset() {
    _activatedSequence = null;
  }
}
