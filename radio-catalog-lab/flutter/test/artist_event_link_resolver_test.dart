import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/artist_event_link_resolver.dart';

Map<String, dynamic> concertsFixture() => {
  'schemaVersion': 1,
  'updatedAt': '2026-11-19',
  'artists': [
    {'id': 'gojira', 'name': 'Gojira', 'aliases': <String>[]},
    {'id': 'the-great-old-ones', 'name': 'The Great Old Ones',
      'aliases': ['T.G.O.O.']},
    {'id': 'muterlein', 'name': 'Mütterlein', 'aliases': <String>[]},
  ],
  'venues': [
    {'id': 'le-rock', 'name': 'Le Rock'},
  ],
  'events': [
    {'id': 'a', 'title': 'Gojira + Guest', 'date': '2026-12-11',
      'status': 'confirmed', 'venueId': 'le-rock',
      'officialUrl': 'https://venue.example/a',
      'artistIds': ['gojira', 'guest-surprise']},
    {'id': 'old', 'title': 'Gojira past', 'date': '2026-01-02',
      'status': 'confirmed', 'artistIds': ['gojira']},
    {'id': 'cancel', 'title': 'Gojira cancelled', 'date': '2027-01-02',
      'status': 'cancelled', 'artistIds': ['gojira']},
    {'id': 'unverified', 'title': 'Unverified performance',
      'date': '2027-01-02', 'status': 'candidate',
      'artistIds': ['gojira']},
  ],
};

Map<String, dynamic> festivalsFixture() => {
  'schema': 3,
  'festivals': [
    {
      'slug': 'go-metal-festival',
      'name': 'GO Metal Festival',
      'status': 'Confirmé',
      'startDate': '2027-06-12',
      'endDate': '2027-06-13',
      'city': 'Montpellier',
      'officialSite': 'https://festival.example/',
      'lineup': ['Gojira', 'Mütterlein'],
      'lineupByDate': {
        '2027-06-12': ['Gojira'],
      },
    },
    {
      'slug': 'past-festival',
      'name': 'Past Festival',
      'status': 'Confirmé',
      'startDate': '2026-08-11',
      'endDate': '2026-08-12',
      'lineup': ['Gojira'],
    },
    {
      'slug': 'cancelled-festival',
      'name': 'Cancelled Festival',
      'status': 'Annulé',
      'startDate': '2027-06-12',
      'endDate': '2027-06-13',
      'lineup': ['Gojira'],
    },
  ],
};

void main() {
  final today = DateTime(2026, 11, 19);

  test('artist on radio links to its upcoming confirmed concerts and festivals',
      () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: festivalsFixture(),
      today: today,
    );
    final found = resolver.resolve('GOJIRA');
    expect(found, isNotNull);
    expect(found!.artistId, 'gojira');
    expect(found.artistName, 'Gojira');
    expect(found.concerts.map((e) => e.eventId), ['a']);
    expect(found.concerts.single.location, 'Le Rock');
    expect(found.concerts.single.officialUrl!.host, 'venue.example');
    expect(found.festivals.map((e) => e.eventId), ['go-metal-festival']);
    expect(found.festivals.single.isExactPerformanceDate, isTrue);
    expect(found.festivals.single.date, DateTime.utc(2027, 6, 12));
  });

  test('accented artist exact canonical name matches accent-insensitive feed',
      () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: festivalsFixture(),
      today: today,
    );
    final found = resolver.resolve('Mutterlein');
    expect(found, isNotNull);
    expect(found!.artistName, 'Mütterlein');
    expect(found.festivals, hasLength(1));
    expect(found.festivals.single.isExactPerformanceDate, isFalse);
    expect(found.festivals.single.endDate, DateTime.utc(2027, 6, 13));
  });

  test('no clickable group without future confirmed shows', () {
    final concerts = concertsFixture();
    concerts['events'] = [];
    final resolver = GoArtistEventResolver.build(
      concerts: concerts,
      festivals: {'festivals': []},
      today: today,
    );
    expect(resolver.resolve('Gojira'), isNull);
    expect(resolver.resolve('Unknown Group'), isNull);
    expect(resolver.resolve(''), isNull);
    expect(resolver.resolve(null), isNull);
  });

  test('metadata must be an exact artist or reviewed alias, never substring',
      () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: festivalsFixture(),
      today: today,
    );
    expect(resolver.resolve('The Gojira Experience'), isNull);
    expect(resolver.resolve('Gojira feat. Guest'), isNull);
    expect(resolver.resolve('Gojira - Stranded'), isNull);
  });

  test('ambiguous canonical alias prevents link to the wrong group', () {
    final concerts = concertsFixture();
    (concerts['artists'] as List).add({
      'id': 'gojira-tribute', 'name': 'Gojira Tribute',
      'aliases': ['Gojira'],
    });
    final resolver = GoArtistEventResolver.build(
      concerts: concerts,
      festivals: festivalsFixture(),
      today: today,
    );
    expect(resolver.resolve('Gojira'), isNull);
  });

  test('past events and cancelled festivals do not create future links', () {
    final concerts = concertsFixture();
    concerts['events'] = [
      (concerts['events'] as List)[1],
      (concerts['events'] as List)[2],
    ];
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      (festivals['festivals'] as List)[1],
      (festivals['festivals'] as List)[2],
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: festivals, today: today,
    );
    expect(resolver.resolve('Gojira'), isNull);
  });

  test('festival day already passed never appears as a future performance',
      () {
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      {
        'slug': 'multi-day',
        'name': 'Multi Day Festival',
        'status': 'Confirmé',
        'startDate': '2026-11-18',
        'endDate': '2026-11-21',
        'lineup': ['Gojira', 'Mütterlein'],
        'lineupByDate': {
          '2026-11-18': ['Gojira'],
          '2026-11-20': ['Mütterlein'],
        },
      },
    ];
    final concerts = concertsFixture();
    concerts['events'] = [];
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: festivals, today: today,
    );
    expect(resolver.resolve('Gojira'), isNull);
    expect(resolver.resolve('Mütterlein')!.festivals.single.date,
        DateTime.utc(2026, 11, 20));
  });

  test('no announced day means festival interval, NOT an invented show day',
      () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: festivalsFixture(),
      today: today,
    );
    final profile = resolver.resolve('Mütterlein')!;
    expect(profile.festivals.single.isExactPerformanceDate, isFalse);
    expect(profile.festivals.single.date, DateTime.utc(2027, 6, 12));
    expect(profile.festivals.single.endDate, DateTime.utc(2027, 6, 13));
  });

  test('repeated artist IDs in one concert are not duplicated', () {
    final concerts = concertsFixture();
    (concerts['events'] as List).first['artistIds'] = [
      'gojira', 'gojira', 'guest-surprise',
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: festivalsFixture(), today: today,
    );
    expect(resolver.resolve('Gojira')!.concerts.length, 1);
  });

  test('unknown guest never blocks known headlining artist', () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: {'festivals': []},
      today: today,
    );
    expect(resolver.resolve('Gojira')!.concerts.single.eventId, 'a');
  });

  test('unsafe official links are withheld, not made clickable', () {
    final concerts = concertsFixture();
    (concerts['events'] as List).first['officialUrl'] =
        'javascript:alert(1)';
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: festivalsFixture(), today: today,
    );
    expect(resolver.resolve('Gojira')!.concerts.single.officialUrl, isNull);
  });

  test('incorrect or missing public feed shape fails explicitly', () {
    expect(() => GoArtistEventResolver.build(
      concerts: {'artists': [], 'events': {}},
      festivals: {'festivals': []}, today: today,
    ), throwsFormatException);
    expect(() => GoArtistEventResolver.build(
      concerts: {'artists': [], 'events': []},
      festivals: {}, today: today,
    ), throwsFormatException);
  });

  test('duplicate canonical artist ID cannot silently change identity', () {
    final concerts = concertsFixture();
    (concerts['artists'] as List).add({
      'id':'gojira', 'name':'Wrong Gojira', 'aliases':[],
    });
    expect(() => GoArtistEventResolver.build(
      concerts: concerts,
      festivals: festivalsFixture(), today: today,
    ), throwsFormatException);
  });

  test('empty and malformed calendar dates are not accepted', () {
    final concerts = concertsFixture();
    (concerts['events'] as List).first['date'] = '2027-02-30';
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: {'festivals': []}, today: today,
    );
    expect(resolver.resolve('Gojira'), isNull);
  });

  test('artist aliases match only explicitly registered catalogue aliases',
      () {
    final concerts = concertsFixture();
    (concerts['events'] as List).first['artistIds'] =
        ['the-great-old-ones'];
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: {'festivals': []}, today: today,
    );
    expect(resolver.resolve('T.G.O.O.')!.artistId, 'the-great-old-ones');
    expect(resolver.resolve('TG00'), isNull);
  });
}
