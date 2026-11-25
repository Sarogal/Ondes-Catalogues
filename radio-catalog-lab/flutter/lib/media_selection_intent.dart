/// A monotonic intent token, reserved before asynchronous station lookup.
/// Only the latest request may publish its resolved selection.
class MediaSelectionIntent {
  int _revision = 0;
  bool _closed = false;
  bool _resolving = false;

  int get current => _revision;

  bool get resolving => _resolving;

  int begin() {
    _resolving = !_closed;
    return ++_revision;
  }

  void finish(int token) {
    if (accepts(token)) _resolving = false;
  }

  int cancel() {
    final token = begin();
    finish(token);
    return token;
  }

  bool accepts(int token) => !_closed && token == _revision;

  void close() {
    _closed = true;
    _resolving = false;
    ++_revision;
  }
}
