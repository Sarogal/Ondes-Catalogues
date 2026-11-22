import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_signed_artwork_version_guard.dart';

void main() {
  test('older signed logo generations cannot replace newer Android Auto images', () {
    final guard = CentralSignedArtworkVersionGuard();
    expect(guard.permits(5), isTrue);
    guard.markActivated(5);
    expect(guard.permits(4), isFalse);
    expect(() => guard.markActivated(4), throwsStateError);
    expect(guard.permits(6), isTrue);
    guard.markActivated(6);
    expect(guard.permits(5), isFalse);
    expect(guard.activatedSequence, 6);
  });

  test('same signed generation may refresh missed SHA objects later', () {
    final guard = CentralSignedArtworkVersionGuard()..markActivated(5);
    expect(guard.permits(5), isTrue);
    guard.markActivated(5);
    expect(guard.activatedSequence, 5);
  });

  test('invalid sequence denied and explicit opt-out may reset artwork', () {
    final guard = CentralSignedArtworkVersionGuard()..markActivated(6);
    expect(guard.permits(0), isFalse);
    expect(guard.permits(-1), isFalse);
    guard.reset();
    expect(guard.activatedSequence, isNull);
    expect(guard.permits(5), isTrue);
  });
}
