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
    {'id': 'le-rock', 'name': 'Le Rock', 'city': 'Montpellier',
      'region': 'Occitanie'},
  ],
  'events': [
    {'id': 'a', 'title': 'Gojira + Guest', 'date': '2026-12-11',
      'status': 'confirmed', 'venueId': 'le-rock',
      'officialUrl': 'https://venue.example/a',
      'ticketUrl': 'https://tickets.example/a',
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
    final found = resolver.resolve('GOJIRA', asOf: today);
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
    final found = resolver.resolve('Mutterlein', asOf: today);
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
    expect(resolver.resolve('Gojira', asOf: today), isNull);
    expect(resolver.resolve('Unknown Group', asOf: today), isNull);
    expect(resolver.resolve('', asOf: today), isNull);
    expect(resolver.resolve(null, asOf: today), isNull);
  });

  test('metadata must be an exact artist or reviewed alias, never substring',
      () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: festivalsFixture(),
      today: today,
    );
    expect(resolver.resolve('The Gojira Experience', asOf: today), isNull);
    expect(resolver.resolve('Gojira feat. Guest', asOf: today), isNull);
    expect(resolver.resolve('Gojira - Stranded', asOf: today), isNull);
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
    expect(resolver.resolve('Gojira', asOf: today), isNull);
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
    expect(resolver.resolve('Gojira', asOf: today), isNull);
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
    expect(resolver.resolve('Gojira', asOf: today), isNull);
    expect(resolver.resolve('Mütterlein', asOf: today)!.festivals.single.date,
        DateTime.utc(2026, 11, 20));
  });

  test('no announced day means festival interval, NOT an invented show day',
      () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: festivalsFixture(),
      today: today,
    );
    final profile = resolver.resolve('Mütterlein', asOf: today)!;
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
    expect(resolver.resolve('Gojira', asOf: today)!.concerts.length, 1);
  });

  test('unknown guest never blocks known headlining artist', () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(),
      festivals: {'festivals': []},
      today: today,
    );
    expect(resolver.resolve('Gojira', asOf: today)!.concerts.single.eventId, 'a');
  });

  test('unsafe official links are withheld, not made clickable', () {
    final concerts = concertsFixture();
    (concerts['events'] as List).first['officialUrl'] =
        'javascript:alert(1)';
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: festivalsFixture(), today: today,
    );
    expect(resolver.resolve('Gojira', asOf: today)!.concerts.single.officialUrl, isNull);
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
    expect(resolver.resolve('Gojira', asOf: today), isNull);
  });

  test('artist aliases match only explicitly registered catalogue aliases',
      () {
    final concerts = concertsFixture();
    (concerts['events'] as List).first['artistIds'] =
        ['the-great-old-ones'];
    final resolver = GoArtistEventResolver.build(
      concerts: concerts, festivals: {'festivals': []}, today: today,
    );
    expect(resolver.resolve('T.G.O.O.', asOf: today)!.artistId, 'the-great-old-ones');
    expect(resolver.resolve('TG00', asOf: today), isNull);
  });

  test('festival-only artist is findable with provisional identity', () {
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      {'slug': 'metal-express', 'name': 'Metal Express',
       'status': 'Confirmé', 'startDate': '2026-11-20',
       'endDate': '2026-11-20', 'city': 'Quimperlé',
       'region': 'Bretagne', 'lineup': ['Odd Nelson']},
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivals, today: today,
    );
    final profile = resolver.resolve('Odd Nelson', asOf: today)!;
    expect(profile.isProvisionalIdentity, isTrue);
    expect(profile.artistId, startsWith('festival-name:'));
    expect(profile.concerts, isEmpty);
    expect(profile.festivals.single.city, 'Quimperlé');
    expect(profile.festivals.single.region, 'Bretagne');
    expect(resolver.resolve('Odd Nelson Tribute', asOf: today), isNull);
  });

  test('canonical concert identity takes priority over festival-only IDs', () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivalsFixture(),
      today: today,
    );
    expect(resolver.resolve('Gojira', asOf: today)!.isProvisionalIdentity,
      isFalse);
  });

  test('conflicting festival-only spellings never join two identities', () {
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      {'slug': 'a', 'status': 'Confirmé',
       'startDate': '2027-06-01', 'endDate': '2027-06-01',
       'lineup': ['Odd Nelson', 'Odd-Nelson']},
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivals, today: today,
    );
    expect(resolver.resolve('Odd Nelson', asOf: today), isNull);
  });

  test('unknown guest placeholders never create artist identities', () {
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      {'slug': 'a', 'status': 'Confirmé',
       'startDate': '2027-06-01', 'endDate': '2027-06-01',
       'lineup': ['Guest surprise', 'TBA', 'A confirmer', 'Odd Nelson']},
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivals, today: today,
    );
    expect(resolver.resolve('Guest surprise', asOf: today), isNull);
    expect(resolver.resolve('TBA', asOf: today), isNull);
    expect(resolver.resolve('Odd Nelson', asOf: today), isNotNull);
  });

  test('festival lineupByDate can name a previously unknown band', () {
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      {'slug': 'a', 'status': 'Confirmé',
       'startDate': '2027-06-01', 'endDate': '2027-06-02',
       'lineup': <String>[],
       'lineupByDate': {'2027-06-02': ['Odd Nelson']}},
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivals, today: today,
    );
    final performance = resolver.resolve('Odd Nelson', asOf: today)!
        .festivals.single;
    expect(performance.date, DateTime.utc(2027, 6, 2));
    expect(performance.isExactPerformanceDate, isTrue);
    expect(performance.performanceDates, [DateTime.utc(2027, 6, 2)]);
  });

  test('overnight rollover filters passed concerts without rebuilding index', () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivalsFixture(),
      today: today,
    );
    final before = resolver.resolve('Gojira', asOf: today)!;
    expect(before.concerts, hasLength(1));
    final later = resolver.resolve('Gojira', asOf: DateTime(2026, 12, 12))!;
    expect(later.concerts, isEmpty);
    expect(later.festivals, hasLength(1));
    expect(resolver.resolve('Gojira', asOf: DateTime(2027, 6, 14)), isNull);
  });

  test('festival range remains its published interval, not a fake today', () {
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      {'slug': 'range', 'status': 'Confirmé',
       'startDate': '2026-11-18', 'endDate': '2026-11-21',
       'lineup': ['Odd Nelson']},
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivals, today: today,
    );
    final item = resolver.resolve('Odd Nelson', asOf: today)!.festivals.single;
    expect(item.isExactPerformanceDate, isFalse);
    expect(item.date, DateTime.utc(2026, 11, 18));
    expect(item.endDate, DateTime.utc(2026, 11, 21));
    expect(resolver.resolve('Odd Nelson', asOf: DateTime(2026, 11, 22)),
      isNull);
  });

  test('multiple confirmed festival slots are separate explicit dates', () {
    final festivals = festivalsFixture();
    festivals['festivals'] = [
      {'slug': 'twice', 'status': 'Confirmé',
       'startDate': '2027-06-01', 'endDate': '2027-06-04',
       'lineup': ['Gojira'],
       'lineupByDate': {
         '2027-06-01': ['Gojira', 'Gojira'],
         '2027-06-04': ['Gojira'],
       }},
    ];
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: festivals, today: today,
    );
    final item = resolver.resolve('Gojira', asOf: today)!.festivals.single;
    expect(item.isExactPerformanceDate, isTrue);
    expect(item.performanceDates, [
      DateTime.utc(2027, 6, 1), DateTime.utc(2027, 6, 4),
    ]);
    expect(item.endDate, isNull);
    final remaining = resolver.resolve('Gojira',
        asOf: DateTime(2027, 6, 2))!.festivals.single;
    expect(remaining.date, DateTime.utc(2027, 6, 4));
    expect(remaining.performanceDates, [DateTime.utc(2027, 6, 4)]);
    expect(resolver.resolve('Gojira', asOf: DateTime(2027, 6, 5)), isNull);
  });

  test('concert profile keeps source ticket and verified venue geography', () {
    final resolver = GoArtistEventResolver.build(
      concerts: concertsFixture(), festivals: {'festivals': []},
      today: today,
    );
    final concert = resolver.resolve('Gojira', asOf: today)!.concerts.single;
    expect(concert.city, 'Montpellier');
    expect(concert.region, 'Occitanie');
    expect(concert.ticketUrl!.host, 'tickets.example');
    expect(concert.performanceDates, [DateTime.utc(2026, 12, 11)]);
  });

}
