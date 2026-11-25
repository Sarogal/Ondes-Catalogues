/// One initialization per process; repeated reads share the same future.
/// Explicit refreshes coalesce and retain the previous authenticated value
/// if the refresh cannot produce a replacement.
class RadioStartupSession<T> {
  Future<T?>? _pending;
  bool _initialized = false;
  T? _current;

  T? get current => _current;

  Future<T?> load(Future<T?> Function() prepare, {bool refresh = false}) {
    final pending = _pending;
    if (pending != null) return pending;
    if (_initialized && !refresh) return Future<T?>.value(_current);
    final operation = Future<T?>.sync(prepare).then((value) {
      if (value != null) _current = value;
      _initialized = true;
      return _current;
    }, onError: (Object _, StackTrace __) {
      _initialized = true;
      return _current;
    });
    _pending = operation;
    return operation.whenComplete(() {
      if (identical(_pending, operation)) _pending = null;
    });
  }
}
