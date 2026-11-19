// Prototype isolated artist -> concert/festival resolver.
// No player changes, no HTTP calls, no UI. Nothing imports this in production.
// Data shapes follow published docs/grossesondes/{concerts,festivals}.json.
// Never link on fuzzy, partial, conflicting or unconfirmed artist metadata.
class GoArtistEventLink {
  const GoArtistEventLink({
    required this.eventId,
    required this.title,
    required this.date,
    required this.isExactPerformanceDate,
    required this.location,
    this.officialUrl,
    this.ticketUrl,
    this.city = '',
    this.region = '',
    this.performanceDates = const [],
    this.endDate,
  });

  final String eventId;
  final String title;
  final DateTime date;
  final DateTime? endDate;
  final bool isExactPerformanceDate;
  final String location;
  final Uri? officialUrl;
  final Uri? ticketUrl;
  final String city;
  final String region;

  /// Dates individually verified for an artist, never a guessed date range.
  final List<DateTime> performanceDates;
}

class GoArtistEventProfile {
  const GoArtistEventProfile({
    required this.artistId,
    required this.artistName,
    required this.concerts,
    required this.festivals,
    this.isProvisionalIdentity = false,
  });

  final String artistId;
  final String artistName;
  final List<GoArtistEventLink> concerts;
  final List<GoArtistEventLink> festivals;

  /// True when an artist is known only by a festival lineup name and has no
  /// shared canonical concerts artist ID. Never claim this is a verified ID.
  final bool isProvisionalIdentity;

  bool get hasUpcomingShows => concerts.isNotEmpty || festivals.isNotEmpty;
}

class GoArtistEventResolver {
  GoArtistEventResolver._(this._byName, this._profiles);

  final Map<String, String?> _byName;
  final Map<String, GoArtistEventProfile> _profiles;

  /// Deterministic snapshot build; call only when the remote agenda changes,
  /// never on each ICY metadata event or playback frame.
  ///
  /// [concerts] is the decoded public concerts.json object with artists,
  /// venues and events. [festivals] is the decoded public festivals.json.
  static GoArtistEventResolver build({
    required Map<String, dynamic> concerts,
    required Map<String, dynamic> festivals,
    required DateTime today,
  }) {
    final artists = concerts['artists'];
    final venues = concerts['venues'];
    final events = concerts['events'];
    final editions = festivals['festivals'];
    if (artists is! List || events is! List || editions is! List) {
      throw const FormatException('Artist/event public feed schema mismatch');
    }
    final todayUtc = DateTime.utc(today.year, today.month, today.day);
    final catalog = <String, String>{};
    final byName = <String, String?>{};
    final provisionalIds = <String>{};

    void registerAlias(String alias, String id) {
      final normalized = _normalize(alias);
      if (normalized.isEmpty) return;
      if (!byName.containsKey(normalized)) {
        byName[normalized] = id;
      } else if (byName[normalized] != id) {
        // Deliberately ambiguous; a click would risk another band's shows.
        byName[normalized] = null;
      }
    }

    for (final artist in artists) {
      if (artist is! Map) continue;
      final id = artist['id'];
      final name = artist['name'];
      if (id is! String || id.isEmpty || name is! String || name.isEmpty ||
          catalog.containsKey(id)) {
        throw const FormatException('Duplicate/invalid canonical artist');
      }
      catalog[id] = name;
      registerAlias(name, id);
      final aliases = artist['aliases'];
      if (aliases is List) {
        for (final alias in aliases) {
          if (alias is String) registerAlias(alias, id);
        }
      }
    }

    // Festival-only groups are absent from concerts.artists. Give them local,
    // explicitly provisional identities rather than silently dropping them.
    // Names still require exact normalized equality, never fuzzy matches.
    // A conflicting spelling under the same normalized name blocks linking.
    const placeholders = <String>{
      'tba', 'a confirmer', 'artiste surprise', 'guest surprise',
      'special guest', 'surprise', 'guest',
    };
    for (final edition in editions) {
      if (edition is! Map) continue;
      final status = _normalize(edition['status'] is String
          ? edition['status'] as String : '');
      final end = _date(edition['endDate']) ?? _date(edition['startDate']);
      if (!{'confirme', 'confirmed'}.contains(status) ||
          end == null || end.isBefore(todayUtc)) continue;
      final names = <String>[];
      if (edition['lineup'] is List) {
        names.addAll((edition['lineup'] as List).whereType<String>());
      }
      if (edition['lineupByDate'] is Map) {
        for (final entry in (edition['lineupByDate'] as Map).entries) {
          final day = _date(entry.key);
          if (day == null || day.isBefore(todayUtc) || entry.value is! List) {
            continue;
          }
          names.addAll((entry.value as List).whereType<String>());
        }
      }
      for (final name in names) {
        final key = _normalize(name);
        if (key.isEmpty || placeholders.contains(key)) continue;
        // Existing canonical names/aliases have priority; null means an
        // ambiguity already known and must never be overwritten.
        if (byName.containsKey(key)) {
          final existingId = byName[key];
          if (existingId != null && provisionalIds.contains(existingId) &&
              catalog[existingId]!.trim().toLowerCase() !=
                  name.trim().toLowerCase()) {
            byName[key] = null;
          }
          continue;
        }
        final id = 'festival-name:${key.replaceAll(' ', '-')}';
        if (catalog.containsKey(id)) {
          byName[key] = null;
          continue;
        }
        catalog[id] = name.trim();
        provisionalIds.add(id);
        byName[key] = id;
      }
    }

    final concertLinks = <String, List<GoArtistEventLink>>{};
    final festivalLinks = <String, List<GoArtistEventLink>>{};
    final seenConcerts = <String>{};
    final venuesById = <String, String>{};
    final venueCitiesById = <String, String>{};
    final venueRegionsById = <String, String>{};

    void addVenue(String id, Map venue) {
      if (venue['name'] is String) {
        venuesById[id] = venue['name'] as String;
      }
      if (venue['city'] is String) {
        venueCitiesById[id] = venue['city'] as String;
      }
      if (venue['region'] is String) {
        venueRegionsById[id] = venue['region'] as String;
      }
    }
    if (venues is List) {
      for (final venue in venues) {
        if (venue is! Map) continue;
        final id = venue['id'];
        final name = venue['name'];
        if (id is String && name is String) addVenue(id, venue);
      }
    } else if (venues is Map) {
      for (final entry in venues.entries) {
        final venue = entry.value;
        if (venue is Map && venue['name'] is String) {
          addVenue(entry.key.toString(), venue);
        }
      }
    }

    for (final event in events) {
      if (event is! Map || event['status'] != 'confirmed') continue;
      final id = event['id'];
      final date = _date(event['date']);
      final artistIds = event['artistIds'];
      if (id is! String || id.isEmpty || date == null ||
          date.isBefore(todayUtc) || artistIds is! List ||
          !seenConcerts.add(id)) {
        continue;
      }
      final title = event['title'] is String ? event['title'] as String : id;
      final venueId = event['venueId'];
      final location = venuesById[venueId] ??
          (venueId is String ? venueId : '');
      final link = GoArtistEventLink(
        eventId: id,
        title: title,
        date: date,
        isExactPerformanceDate: true,
        location: location,
        city: venueCitiesById[venueId] ?? '',
        region: venueRegionsById[venueId] ?? '',
        officialUrl: _url(event['officialUrl']),
        ticketUrl: _url(event['ticketUrl']),
        performanceDates: List.unmodifiable([date]),
      );
      for (final artistId in artistIds.toSet()) {
        if (artistId is String && catalog.containsKey(artistId)) {
          concertLinks.putIfAbsent(artistId, () => []).add(link);
        }
      }
    }

    final seenEditions = <String>{};
    for (final edition in editions) {
      if (edition is! Map) continue;
      final id = edition['slug'];
      final start = _date(edition['startDate']);
      final end = _date(edition['endDate']) ?? start;
      final status = _normalize(edition['status'] is String
          ? edition['status'] as String : '');
      if (id is! String || id.isEmpty || !seenEditions.add(id) ||
          start == null || end == null || end.isBefore(todayUtc) ||
          !{'confirme', 'confirmed'}.contains(status)) {
        continue;
      }
      final announced = <String>{};
      final lineup = edition['lineup'];
      if (lineup is List) {
        for (final name in lineup) {
          if (name is String) announced.add(name);
        }
      }
      final datesByArtist = <String, List<DateTime>>{};
      final artistsWithDatedSlots = <String>{};
      final schedule = edition['lineupByDate'];
      if (schedule is Map) {
        for (final entry in schedule.entries) {
          final date = _date(entry.key);
          if (date == null || date.isBefore(start) || date.isAfter(end) ||
              entry.value is! List) {
            continue;
          }
          for (final name in entry.value as List) {
            if (name is! String) continue;
            final artistId = byName[_normalize(name)];
            if (artistId == null) continue;
            artistsWithDatedSlots.add(artistId);
            // A band that played yesterday must not be advertised as an
            // upcoming performance just because the festival runs today.
            if (date.isBefore(todayUtc)) continue;
            announced.add(name);
            final days = datesByArtist.putIfAbsent(artistId, () => []);
            if (!days.contains(date)) days.add(date);
          }
        }
      }

      final artistIds = <String>{};
      for (final name in announced) {
        final artistId = byName[_normalize(name)];
        if (artistId != null) artistIds.add(artistId);
      }
      final title = edition['name'] is String
          ? edition['name'] as String : id;
      final place = edition['city'] is String
          ? edition['city'] as String : '';
      final site = _url(edition['officialSite']);

      for (final artistId in artistIds) {
        final performedDates = datesByArtist[artistId] ?? const <DateTime>[];
        if (performedDates.isEmpty && artistsWithDatedSlots.contains(artistId)) {
          // Scheduled, but every identified slot has passed.
          continue;
        }
        if (performedDates.isNotEmpty) {
          performedDates.sort();
          festivalLinks.putIfAbsent(artistId, () => []).add(
            GoArtistEventLink(
              eventId: id,
              title: title,
              date: performedDates.first,
              isExactPerformanceDate: true,
              location: place,
              city: place,
              region: edition['region'] is String
                  ? edition['region'] as String : '',
              officialUrl: site,
              performanceDates: List.unmodifiable(performedDates),
            ),
          );
        } else {
          // The artist is on the festival bill but its performance date is
          // unknown. Never present the festival's start as a confirmed set.
          festivalLinks.putIfAbsent(artistId, () => []).add(
            GoArtistEventLink(
              eventId: id,
              title: title,
              date: start,
              endDate: end,
              isExactPerformanceDate: false,
              location: place,
              city: place,
              region: edition['region'] is String
                  ? edition['region'] as String : '',
              officialUrl: site,
            ),
          );
        }
      }
    }

    final profiles = <String, GoArtistEventProfile>{};
    for (final entry in catalog.entries) {
      final concertsForArtist = concertLinks[entry.key] ?? [];
      final festivalsForArtist = festivalLinks[entry.key] ?? [];
      concertsForArtist.sort((a, b) => a.date.compareTo(b.date));
      festivalsForArtist.sort((a, b) => a.date.compareTo(b.date));
      profiles[entry.key] = GoArtistEventProfile(
        artistId: entry.key,
        artistName: entry.value,
        concerts: List.unmodifiable(concertsForArtist),
        festivals: List.unmodifiable(festivalsForArtist),
        isProvisionalIdentity: provisionalIds.contains(entry.key),
      );
    }
    return GoArtistEventResolver._(
      Map.unmodifiable(byName),
      Map.unmodifiable(profiles),
    );
  }

  /// Feed with GoNowPlaying.artist; return null for metadata without a unique
  /// canonical match or without an upcoming confirmed concert/festival.
  GoArtistEventProfile? resolve(String? nowPlayingArtist, {DateTime? asOf}) {
    final normalized = _normalize(nowPlayingArtist ?? '');
    final id = _byName[normalized];
    if (id == null) return null;
    final profile = _profiles[id];
    if (profile == null) return null;
    // Indexing is expensive and done on feed changes. Date filtering is cheap
    // and must also happen when the app stays open across midnight.
    final now = asOf ?? DateTime.now();
    final day = DateTime.utc(now.year, now.month, now.day);
    GoArtistEventLink? remaining(GoArtistEventLink link) {
      if (!link.isExactPerformanceDate) {
        return (link.endDate ?? link.date).isBefore(day) ? null : link;
      }
      final futureDays = link.performanceDates
          .where((date) => !date.isBefore(day)).toList(growable: false);
      if (futureDays.isEmpty) return null;
      if (futureDays.length == link.performanceDates.length) return link;
      // A band playing twice at the same festival may have one date already
      // passed. Promote the earliest remaining *verified* slot, not a range.
      return GoArtistEventLink(
        eventId: link.eventId,
        title: link.title,
        date: futureDays.first,
        isExactPerformanceDate: true,
        location: link.location,
        city: link.city,
        region: link.region,
        officialUrl: link.officialUrl,
        ticketUrl: link.ticketUrl,
        performanceDates: List.unmodifiable(futureDays),
      );
    }
    final concerts = profile.concerts
        .map(remaining).whereType<GoArtistEventLink>().toList(growable: false);
    final festivals = profile.festivals
        .map(remaining).whereType<GoArtistEventLink>().toList(growable: false);
    if (concerts.isEmpty && festivals.isEmpty) return null;
    return GoArtistEventProfile(
      artistId: profile.artistId,
      artistName: profile.artistName,
      concerts: List.unmodifiable(concerts),
      festivals: List.unmodifiable(festivals),
      isProvisionalIdentity: profile.isProvisionalIdentity,
    );
  }

  static DateTime? _date(Object? value) {
    if (value is! String ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) return null;
    final y = int.parse(value.substring(0, 4));
    final m = int.parse(value.substring(5, 7));
    final d = int.parse(value.substring(8, 10));
    final parsed = DateTime.utc(y, m, d);
    return parsed.year == y && parsed.month == m && parsed.day == d
        ? parsed : null;
  }

  static Uri? _url(Object? value) {
    if (value is! String) return null;
    final parsed = Uri.tryParse(value);
    if (parsed == null || parsed.scheme != 'https' || parsed.host.isEmpty ||
        parsed.userInfo.isNotEmpty) return null;
    return parsed;
  }

  static String _normalize(String value) {
    var text = value.toLowerCase().trim();
    const replacements = <String, String>{
      'à':'a','á':'a','â':'a','ä':'a','ã':'a','å':'a',
      'ç':'c','è':'e','é':'e','ê':'e','ë':'e',
      'ì':'i','í':'i','î':'i','ï':'i',
      'ñ':'n','ò':'o','ó':'o','ô':'o','ö':'o','õ':'o','ø':'o',
      'ù':'u','ú':'u','û':'u','ü':'u','ý':'y','ÿ':'y',
      'æ':'ae','œ':'oe','ß':'ss',
    };
    for (final entry in replacements.entries) {
      text = text.replaceAll(entry.key, entry.value);
    }
    return text.replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim()
        .replaceAll(RegExp(r'\s+'), ' ');
  }
}
