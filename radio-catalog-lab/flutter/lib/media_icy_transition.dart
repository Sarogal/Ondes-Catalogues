/// Conservative ICY transition filter. A source switch must observe a clean
/// metadata boundary before accepting the previous track text again.
/// This is not native event provenance: device playback remains to validate.
class MediaIcyTransition {
  int? _generation;
  String? _previous;
  bool _open = false;
  bool _cleanBoundary = false;

  void begin(int generation, String? previousRaw) {
    _generation = generation;
    _previous = normalize(previousRaw);
    _open = false;
    _cleanBoundary = false;
  }

  static String? normalize(String? raw) {
    final value = raw?.replaceAll(RegExp(r'\s+'), ' ').trim();
    return value == null || value.isEmpty ? null : value;
  }

  bool open(int generation, {required String? stoppedPlayerRaw}) {
    if (_generation != generation) return false;
    _open = true;
    _cleanBoundary = normalize(stoppedPlayerRaw) == null;
    return true;
  }

  bool accepts(int generation, String? raw) {
    if (_generation != generation || !_open) return false;
    final value = normalize(raw);
    if (value == null) {
      _cleanBoundary = true;
      return false; // Empty ICY blocks are not a new song.
    }
    if (!_cleanBoundary && value == _previous) return false;
    // A distinct value is evidence of progress, not verified artist identity.
    _cleanBoundary = true;
    return true;
  }

  void close() {
    _generation = null;
    _previous = null;
    _open = false;
    _cleanBoundary = false;
  }
}
