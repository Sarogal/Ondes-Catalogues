/// A monotonic intent token, reserved before asynchronous station lookup.
/// Only the latest request may publish its resolved selection.
class MediaSelectionIntent {
  int _revision = 0;
  bool _closed = false;

  int get current => _revision;

  int begin() => ++_revision;

  bool accepts(int token) => !_closed && token == _revision;

  void close() {
    _closed = true;
    ++_revision;
  }
}
