// Test-only minimal compatibility shape for the isolated central adapter.
// This is NOT the application's RadioStation and never ships in an APK.
class RadioStreamVariant {
  const RadioStreamVariant({
    required this.stationId,
    required this.streamUrl,
    required this.codec,
    required this.bitrate,
  });

  final String stationId;
  final String streamUrl;
  final String codec;
  final int bitrate;
}

class RadioStation {
  const RadioStation({
    required this.id,
    required this.name,
    required this.genre,
    required this.tags,
    required this.streamUrl,
    required this.logoUrl,
    required this.homepage,
    required this.countryCode,
    required this.codec,
    required this.bitrate,
    required this.votes,
    this.streamVariants = const [],
    this.catalogLogoUrl = '',
    this.logoSource = 'legacy',
  });

  final String id;
  final String name;
  final String genre;
  final List<String> tags;
  final String streamUrl;
  final String logoUrl;
  final String homepage;
  final String countryCode;
  final String codec;
  final int bitrate;
  final int votes;
  final List<RadioStreamVariant> streamVariants;
  final String catalogLogoUrl;
  final String logoSource;

  Set<String> get allStationIds => {
    if (id.trim().isNotEmpty) id,
    for (final stream in streamVariants)
      if (stream.stationId.trim().isNotEmpty) stream.stationId,
  };

  RadioStation copyWith({
    String? id,
    String? name,
    String? genre,
    List<String>? tags,
    String? streamUrl,
    String? logoUrl,
    String? homepage,
    String? countryCode,
    String? codec,
    int? bitrate,
    int? votes,
    List<RadioStreamVariant>? streamVariants,
    String? catalogLogoUrl,
    String? logoSource,
  }) => RadioStation(
    id: id ?? this.id,
    name: name ?? this.name,
    genre: genre ?? this.genre,
    tags: tags ?? this.tags,
    streamUrl: streamUrl ?? this.streamUrl,
    logoUrl: logoUrl ?? this.logoUrl,
    homepage: homepage ?? this.homepage,
    countryCode: countryCode ?? this.countryCode,
    codec: codec ?? this.codec,
    bitrate: bitrate ?? this.bitrate,
    votes: votes ?? this.votes,
    streamVariants: streamVariants ?? this.streamVariants,
    catalogLogoUrl: catalogLogoUrl ?? this.catalogLogoUrl,
    logoSource: logoSource ?? this.logoSource,
  );
}

class MetalGenreResolver {
  static const displayGenres = ['Heavy', 'Punk', 'Metal', 'Hard Rock'];
}
