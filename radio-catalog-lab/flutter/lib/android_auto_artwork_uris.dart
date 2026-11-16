/// URI d'illustrations utilisées par le catalogue Android Auto.
/// Les vrais logos en cache et les visuels génériques passent tous par
/// StationLogoContentProvider, afin que le client voiture puisse ouvrir
/// l'image sans dépendre de l'accès aux ressources de l'Activity Flutter.
class AndroidAutoArtworkUris {
  const AndroidAutoArtworkUris._();

  static const String authority =
      'fr.grossesondes.grosses_ondes.stationlogos';

  static const Map<String, String> genreDrawables = <String, String>{
    'Heavy': 'go_genre_heavy_v2',
    'Hard Rock': 'go_genre_hard_rock_422',
    'Punk': 'go_genre_punk_v1',
    'Thrash': 'go_genre_thrash_422',
    'Death': 'go_genre_death_v2',
    'Black': 'go_genre_black_422',
    'Doom': 'go_genre_doom_422',
    'Power': 'go_genre_power_422',
    'Symphonic': 'go_genre_symphonic_422',
    'Progressive': 'go_genre_progressive_422',
    'Folk': 'go_genre_folk_422',
    'Industrial': 'go_genre_industrial_422',
    'Metalcore': 'go_genre_metalcore_422',
    'Metal': 'go_genre_metal_v2',
  };

  static const String unknownGenreDrawable = 'go_auto_fallback_official';

  /// L'ancien contrat des logos authentiques reste inchangé.
  static Uri forCachedLogo(String fileName) => Uri(
        scheme: 'content',
        host: authority,
        pathSegments: <String>[fileName],
      );

  /// Future SHA-verified local logo in a separate, immutable object store.
  /// This URI is not emitted by the current V64 audio handler.
  static Uri forCentralSha256(String sha256) {
    if (!RegExp(r'^[a-f0-9]{64}$').hasMatch(sha256)) {
      throw ArgumentError.value(
        sha256, 'sha256', 'Invalid central logo digest',
      );
    }
    return Uri(
      scheme: 'content',
      host: authority,
      pathSegments: <String>['central', '$sha256.img'],
    );
  }

  /// Le fournisseur Android sert lui-même le PNG embarqué du genre.
  static Uri forGenre(String genre) => Uri(
        scheme: 'content',
        host: authority,
        pathSegments: <String>[
          'genre',
          genreDrawables[genre] ?? unknownGenreDrawable,
        ],
      );
}
