// Experimental, opt-in-only central radio catalog verifier.
// Does not import CatalogController or mutate legacy radio/favorite preferences.
import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';

class CentralCatalogException implements Exception {
  const CentralCatalogException(this.reason);
  final String reason;
  @override
  String toString() => 'CentralCatalogException: $reason';
}

class CentralCatalogPointer {
  CentralCatalogPointer._(this.raw, this.sequence, this.sha256, this.length,
      this.path, this.keyId, this.signatureBytes);

  final Map<String, dynamic> raw;
  final int sequence;
  final String sha256;
  final int length;
  final String path;
  final String keyId;
  final List<int> signatureBytes;

  static final RegExp _sha = RegExp(r'^[a-f0-9]{64}$');
  static const int maximumCatalogBytes = 10 * 1024 * 1024;
  static const int maximumPointerBytes = 16 * 1024;

  factory CentralCatalogPointer.parse(Uint8List bytes) {
    if (bytes.isEmpty || bytes.length > maximumPointerBytes) {
      throw const CentralCatalogException('Invalid pointer size');
    }
    final dynamic decoded;
    try {
      decoded = jsonDecode(utf8.decode(bytes, allowMalformed: false));
    } catch (_) {
      throw const CentralCatalogException('Invalid pointer JSON');
    }
    if (decoded is! Map<String, dynamic>) {
      throw const CentralCatalogException('Pointer must be an object');
    }
    const names = {
      'schema_version', 'catalog_id', 'release_sequence',
      'published_at', 'content_sha256', 'content_length',
      'content_path', 'signature'
    };
    if (!decoded.keys.toSet().containsAll(names) ||
        decoded.keys.any((key) => !names.contains(key)) ||
        decoded['schema_version'] != 1 ||
        decoded['catalog_id'] != 'grosses-ondes-radio') {
      throw const CentralCatalogException('Unsupported pointer contract');
    }
    final sequence = decoded['release_sequence'];
    final digest = decoded['content_sha256'];
    final length = decoded['content_length'];
    final path = decoded['content_path'];
    if (sequence is! int || sequence < 1 || length is! int ||
        length < 1 || length > maximumCatalogBytes || digest is! String ||
        !_sha.hasMatch(digest) || path != 'releases/$digest.json' ||
        DateTime.tryParse(decoded['published_at'] is String
            ? decoded['published_at'] as String : '') == null) {
      throw const CentralCatalogException('Malformed pointer metadata');
    }
    final sig = decoded['signature'];
    if (sig is! Map<String, dynamic> ||
        sig.keys.toSet().length != 3 ||
        !sig.keys.toSet().containsAll({'algorithm', 'key_id', 'signature_base64'}) ||
        sig['algorithm'] != 'Ed25519' ||
        sig['key_id'] is! String || (sig['key_id'] as String).isEmpty ||
        sig['signature_base64'] is! String) {
      throw const CentralCatalogException('Signed pointer required');
    }
    late final List<int> signatureBytes;
    try {
      signatureBytes = base64.decode(sig['signature_base64'] as String);
    } catch (_) {
      throw const CentralCatalogException('Invalid signature encoding');
    }
    if (signatureBytes.length != 64) {
      throw const CentralCatalogException('Invalid Ed25519 signature size');
    }
    return CentralCatalogPointer._(
        decoded, sequence, digest, length, path,
        sig['key_id'] as String, signatureBytes);
  }

  /// Canonical v1 signing contract. Every mutable pointer field is covered.
  /// Publisher MUST sign these UTF-8 bytes, with exact newline separators.
  List<int> get signatureMessage => utf8.encode(
      'GO-RADIO-CATALOG-POINTER-V1\n'
      '${raw['schema_version']}\n'
      '${raw['catalog_id']}\n'
      '${raw['release_sequence']}\n'
      '${raw['published_at']}\n'
      '${raw['content_sha256']}\n'
      '${raw['content_length']}\n'
      '${raw['content_path']}\n'
      '$keyId\n');
}

class ValidatedCentralCatalog {
  const ValidatedCentralCatalog(this.pointer, this.pointerBytes,
      this.catalogBytes, this.stations, this.aliasOwners, this.goIds,
      this.activeIds);
  final CentralCatalogPointer pointer;
  final Uint8List pointerBytes;
  final Uint8List catalogBytes;
  final List<Map<String, dynamic>> stations;
  final Map<String, String> aliasOwners;
  final Set<String> goIds;
  final Set<String> activeIds;
}

class CentralCatalogVerifier {
  const CentralCatalogVerifier({required this.trustedKeys});

  /// Pinned Ed25519 public keys supplied by an audited build configuration.
  /// An empty map intentionally makes every remote update fail closed.
  final Map<String, SimplePublicKey> trustedKeys;

  static final _goId = RegExp(r'^go-station-[0-9]{6,}$');
  static final _sha = RegExp(r'^[a-f0-9]{64}$');

  Future<CentralCatalogPointer> verifyPointer(Uint8List pointerBytes) async {
    final pointer = await verifyPointer(pointerBytes);
    return pointer;
  }

  Future<ValidatedCentralCatalog> verify({
    required Uint8List pointerBytes,
    required Uint8List catalogBytes,
    ValidatedCentralCatalog? previous,
  }) async {
    final pointer = CentralCatalogPointer.parse(pointerBytes);
    final key = trustedKeys[pointer.keyId];
    if (key == null || key.type != KeyPairType.ed25519) {
      throw const CentralCatalogException('Untrusted signing key');
    }
    final validSignature = await Ed25519().verify(
      pointer.signatureMessage,
      signature: Signature(pointer.signatureBytes, publicKey: key),
    );
    if (!validSignature) {
      throw const CentralCatalogException('Invalid pointer signature');
    }
    if (catalogBytes.length != pointer.length ||
        crypto.sha256.convert(catalogBytes).toString() != pointer.sha256) {
      throw const CentralCatalogException('Catalog digest or length mismatch');
    }
    if (previous != null && pointer.sequence <= previous.pointer.sequence) {
      throw const CentralCatalogException('Non-monotonic release sequence');
    }

    final dynamic decoded;
    try {
      decoded = jsonDecode(utf8.decode(catalogBytes, allowMalformed: false));
    } catch (_) {
      throw const CentralCatalogException('Invalid catalog JSON');
    }
    final root = _object(decoded, 'catalog');
    if (root['schema_version'] != 1 ||
        root['catalog_id'] != 'grosses-ondes-radio' ||
        root['release_sequence'] is! int ||
        (root['release_sequence'] as int) < 1 ||
        (root['release_sequence'] as int) > pointer.sequence ||
        DateTime.tryParse(root['generated_at'] is String
            ? root['generated_at'] as String : '') == null) {
      throw const CentralCatalogException('Unsupported catalog envelope');
    }
    final records = _list(root['stations'], 'stations');
    final tombstones = _list(root['tombstones'], 'tombstones');
    if (records.isEmpty || records.length > 10000 || tombstones.length > 10000) {
      throw const CentralCatalogException('Implausible catalog station count');
    }
    final aliases = <String, String>{};
    final goIds = <String>{};
    final active = <String>{};
    final stations = <Map<String, dynamic>>[];
    for (final raw in records) {
      final item = _object(raw, 'station');
      final id = _goStationId(item, goIds);
      final legacy = _aliases(item['legacy_aliases'], 'legacy_aliases');
      _assignAliases(aliases, id, legacy);
      final rb = _list(item['radio_browser_uuids'], 'radio_browser_uuids');
      for (final rawId in rb) {
        final entry = _object(rawId, 'radio_browser_uuid');
        final uuid = entry['uuid'];
        if (uuid is! String || !legacy.contains(uuid) ||
            !{'current', 'historical'}.contains(entry['state'])) {
          throw const CentralCatalogException('Invalid Radio Browser alias');
        }
      }
      if (item['display_name'] is! String ||
          (item['display_name'] as String).trim().isEmpty ||
          item['genres'] is! List || (item['genres'] as List).isEmpty) {
        throw const CentralCatalogException('Invalid station identity');
      }
      final status = _object(item['status'], 'status');
      final state = status['state'];
      if (!{'active', 'quarantined', 'retired'}.contains(state)) {
        throw const CentralCatalogException('Invalid station status');
      }
      final editorial = _object(item['editorial'], 'editorial');
      if (editorial['admission_state'] != 'approved' ||
          editorial['reviewed_at'] is! String ||
          DateTime.tryParse(editorial['reviewed_at'] as String) == null) {
        throw const CentralCatalogException('Unreviewed catalog entry');
      }
      if (state != 'active' &&
          (status['reason_code'] is! String ||
              (status['reason_code'] as String).trim().isEmpty)) {
        throw const CentralCatalogException('Unexplained station suspension');
      }
      final streams = _list(item['streams'], 'streams');
      final streamIds = <String>{};
      final priorities = <int>{};
      var verified = 0;
      for (final rawStream in streams) {
        final stream = _object(rawStream, 'stream');
        final streamId = stream['stream_id'];
        final priority = stream['priority'];
        final url = stream['url'];
        final stateName = stream['state'];
        if (streamId is! String || streamId.isEmpty ||
            !streamIds.add(streamId) ||
            priority is! int || priority < 0 || !priorities.add(priority) ||
            !_safePublicUrl(url, allowHttp: true) ||
            Uri.parse(url as String).scheme != stream['protocol'] ||
            !{'candidate', 'candidate_verified', 'verified',
                'suspected_unavailable', 'disabled'}.contains(stateName)) {
          throw const CentralCatalogException('Invalid stream');
        }
        if (stateName == 'verified') verified++;
      }
      if (state == 'active') {
        active.add(id);
        if (verified == 0) {
          throw const CentralCatalogException('Active station lacks verified stream');
        }
      }
      final logo = item['logo'];
      if (logo != null) {
        final l = _object(logo, 'logo');
        final digest = l['sha256'];
        if (digest is! String || !_sha.hasMatch(digest) ||
            l['asset_id'] != 'sha256:$digest' ||
            !_safePublicUrl(l['url'], allowHttp: false) ||
            l['byte_size'] is! int || (l['byte_size'] as int) < 1 ||
            (l['byte_size'] as int) > 8 * 1024 * 1024) {
          throw const CentralCatalogException('Invalid logo metadata');
        }
      }
      stations.add(item);
    }
    for (final raw in tombstones) {
      final item = _object(raw, 'tombstone');
      final id = _goStationId(item, goIds);
      _assignAliases(aliases, id, _aliases(item['legacy_aliases'], 'tombstone.aliases'));
      if (item['reason_code'] is! String ||
          (item['reason_code'] as String).trim().isEmpty) {
        throw const CentralCatalogException('Missing retirement reason');
      }
    }

    if (previous != null) {
      if (!goIds.containsAll(previous.goIds)) {
        throw const CentralCatalogException('Historical GO identity lost');
      }
      for (final entry in previous.aliasOwners.entries) {
        if (aliases[entry.key] != entry.value) {
          throw const CentralCatalogException('Historical alias lost or reassigned');
        }
      }
      final lost = previous.activeIds.difference(active).length;
      if (previous.activeIds.length >= 200 && lost >= 25 &&
          lost * 100 >= previous.activeIds.length * 12) {
        throw const CentralCatalogException('Bulk active station shrink');
      }
    }

    return ValidatedCentralCatalog(
        pointer, Uint8List.fromList(pointerBytes),
        Uint8List.fromList(catalogBytes),
        List<Map<String, dynamic>>.unmodifiable(stations),
        Map<String, String>.unmodifiable(aliases),
        Set<String>.unmodifiable(goIds),
        Set<String>.unmodifiable(active));
  }

  static Map<String, dynamic> _object(dynamic value, String label) {
    if (value is! Map<String, dynamic>) {
      throw CentralCatalogException('$label must be an object');
    }
    return value;
  }

  static List<dynamic> _list(dynamic value, String label) {
    if (value is! List) {
      throw CentralCatalogException('$label must be a list');
    }
    return value;
  }

  static String _goStationId(Map<String, dynamic> item, Set<String> seen) {
    final id = item['go_station_id'];
    if (id is! String || !_goId.hasMatch(id) || !seen.add(id)) {
      throw const CentralCatalogException('Duplicate or invalid permanent station ID');
    }
    return id;
  }

  static Set<String> _aliases(dynamic raw, String label) {
    final values = _list(raw, label);
    final result = <String>{};
    for (final value in values) {
      if (value is! String || value.trim().isEmpty || !result.add(value)) {
        throw const CentralCatalogException('Duplicate or invalid legacy alias');
      }
    }
    return result;
  }

  static void _assignAliases(
      Map<String, String> aliases, String owner, Set<String> keys) {
    for (final id in keys) {
      if (aliases.containsKey(id) && aliases[id] != owner) {
        throw const CentralCatalogException('Legacy alias reassignment');
      }
      aliases[id] = owner;
    }
  }

  static bool _safePublicUrl(dynamic raw, {required bool allowHttp}) {
    if (raw is! String) return false;
    final uri = Uri.tryParse(raw);
    if (uri == null || !uri.hasAuthority || uri.host.isEmpty ||
        uri.userInfo.isNotEmpty || uri.hasFragment ||
        !(uri.scheme == 'https' || (allowHttp && uri.scheme == 'http'))) {
      return false;
    }
    final h = uri.host.toLowerCase().replaceAll(RegExp(r'\.$'), '');
    if (h == 'localhost' || h.endsWith('.local') ||
        h.endsWith('.internal') || !h.contains('.') ||
        h.contains(':') ||
        RegExp(r'^[0-9.]+$').hasMatch(h)) {
      return false;
    }
    return true;
  }
}
