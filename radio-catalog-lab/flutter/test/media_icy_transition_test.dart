import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/media_icy_transition.dart';

void main() {
  test('ignore ICY residue until old native source stopped', () {
    final gate = MediaIcyTransition();
    gate.begin(1, 'Old - Song');
    expect(gate.accepts(1, 'Other - Old song'), isFalse);
    expect(gate.open(1, stoppedPlayerRaw: 'Old - Song'), isTrue);
    expect(gate.accepts(1, 'Old - Song'), isFalse);
    expect(gate.accepts(1, 'New - Song'), isTrue);
  });

  test('same real song can recur after a clean source boundary', () {
    final gate = MediaIcyTransition();
    gate.begin(2, 'Band - Song');
    expect(gate.open(2, stoppedPlayerRaw: null), isTrue);
    expect(gate.accepts(2, 'Band - Song'), isTrue);
  });

  test('empty metadata can establish a reset but is not a new track', () {
    final gate = MediaIcyTransition();
    gate.begin(3, 'Band - Song');
    gate.open(3, stoppedPlayerRaw: 'Band - Song');
    expect(gate.accepts(3, '  '), isFalse);
    expect(gate.accepts(3, 'Band - Song'), isTrue);
    expect(gate.accepts(3, null), isFalse);
  });

  test('obsolete generation cannot reopen or publish', () {
    final gate = MediaIcyTransition();
    gate.begin(4, 'Old - Song');
    gate.begin(5, 'Current - Song');
    expect(gate.open(4, stoppedPlayerRaw: null), isFalse);
    expect(gate.accepts(4, 'Other - Song'), isFalse);
    gate.open(5, stoppedPlayerRaw: null);
    expect(gate.accepts(5, 'New - Song'), isTrue);
    gate.close();
    expect(gate.accepts(5, 'New - Song'), isFalse);
  });

  test('normalizes residue without inventing artist fields', () {
    final gate = MediaIcyTransition();
    gate.begin(6, 'Band  -  Song');
    gate.open(6, stoppedPlayerRaw: 'Band - Song');
    expect(gate.accepts(6, 'Band - Song'), isFalse);
    expect(gate.accepts(6, 'Unsplit title'), isTrue);
  });
}
