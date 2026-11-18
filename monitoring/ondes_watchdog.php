<?php
/** Independent, read-only watchdog for the public Ondes-Catalogues workflows. */
declare(strict_types=1);
date_default_timezone_set('UTC');

const WATCH_REPO = 'Sarogal/Ondes-Catalogues';
const WATCH_WORKFLOWS = [
    'P’tites Ondes — collecte Sorties + Lieux' => ['ptitesondes-private-intake-on-public-runners.yml', ['07:17', '10:17', '14:17', '18:17', '21:37']],
    'Grosses Ondes — collecte Festivals' => ['grossesondes-festivals-private-intake-on-public-runners.yml', ['06:24', '18:42']],
    'Grosses Ondes — collecte Concerts' => ['grossesondes-concerts-private-intake-on-public-runners.yml', ['07:18', '13:11', '20:11']],
    'P’tites Ondes — prévalidation Sorties' => ['ptitesondes-evidence-preview.yml', ['08:40', '11:40', '15:40', '19:40']],
    'P’tites Ondes — prévalidation Lieux' => ['ptitesondes-place-preflight.yml', ['08:50', '11:50', '15:50', '19:50']],
    'P’tites Ondes — publication Sorties/Lieux' => ['ptitesondes-cloud-sync.yml', ['09:20', '12:20', '16:20', '20:20']],
    'Grosses Ondes — publication Festivals' => ['grossesondes-cloud-sync.yml', ['10:47', '17:45']],
    'Grosses Ondes — publication Concerts' => ['grossesondes-concerts-cloud-sync.yml', ['00:17', '03:17', '06:17', '09:17', '12:17', '15:17', '18:17', '21:17']],
];
const WATCH_CATALOGUES = [
    'Sorties' => ['ptitesondes/sorties.json', 'version', 3, 'events', 100],
    'Lieux' => ['ptitesondes/lieux.json', 'version', 1, 'places', 1],
    'Festivals' => ['grossesondes/festivals.json', 'schema', 1, 'festivals', 90],
    'Concerts' => ['grossesondes/concerts.json', 'schemaVersion', 1, 'events', 10],
];

function watch_fetch(string $url): array {
    // No credential is ever required. Keep the entire watchdog outside private data.
    $header = "User-Agent: ondes-public-watchdog/1.0\r\nAccept: application/vnd.github+json\r\n";
    $token = getenv('GITHUB_TOKEN');
    if (str_starts_with($url, 'https://api.github.com/') && is_string($token) && $token !== '') {
        $header .= "Authorization: Bearer $token\r\n";
    }
    $context = stream_context_create(['http' => [
        'timeout' => 12, 'ignore_errors' => true, 'header' => $header,
    ]]);
    $body = @file_get_contents($url, false, $context, 0, 6000001);
    $headers = $http_response_header ?? [];
    $status = 0;
    foreach ($headers as $line) {
        if (preg_match('~^HTTP/\S+\s+(\d{3})~', $line, $m)) {
            $status = (int)$m[1];
        }
    }
    if ($body === false || $status !== 200 || strlen($body) > 6000000) {
        throw new RuntimeException("HTTP $status ou JSON inaccessible : $url");
    }
    $decoded = json_decode($body, true, 128, JSON_THROW_ON_ERROR);
    if (!is_array($decoded)) {
        throw new RuntimeException("Réponse non JSON : $url");
    }
    return $decoded;
}

/**
 * Number of theoretical slots in a mature interval. Never assign a GitHub
 * created_at to an exact cron: GitHub run listings do not expose its origin.
 */
function watch_window_slots(array $hours, int $start, int $end): array {
    $day = (int)(floor($start / 86400) * 86400);
    $slots = [];
    while ($day <= $end) {
        foreach ($hours as $hhmm) {
            [$hour, $minute] = array_map('intval', explode(':', $hhmm));
            $slot = $day + $hour * 3600 + $minute * 60;
            if ($slot > $start && $slot <= $end) {
                $slots[] = $slot;
            }
        }
        $day += 86400;
    }
    sort($slots);
    return $slots;
}

/**
 * 48h aggregate cadence, with a separate mature 24h slice.
 *
 * A created_at timestamp can be many hours later than the scheduled cron
 * and cannot prove which individual slot started. Warnings mark a *small*
 * cadence deficit; two missing successes in either window are a failure.
 * All explicit unsuccessful runs in the last mature day are failures.
 * Neither workflow_dispatch nor external rescue masquerades as schedule.
 */
function watch_workflow_report(string $label, array $spec, array $payload, int $now): array {
    if (!isset($payload['workflow_runs']) || !is_array($payload['workflow_runs'])) {
        return ['alerts' => ["$label : réponse API invalide"], 'warnings' => [],
            'metrics' => null];
    }
    $end = $now - 9 * 3600;
    $start24 = $end - 86400;
    $start48 = $end - 2 * 86400;
    $expected24 = count(watch_window_slots($spec[1], $start24, $end));
    $expected48 = count(watch_window_slots($spec[1], $start48, $end));
    $success24 = $success48 = $failed24 = $failed48 = 0;
    $seen = [];
    foreach ($payload['workflow_runs'] as $index => $run) {
        if (!is_array($run) || ($run['event'] ?? null) !== 'schedule') {
            continue;
        }
        // Refuse to double-count an id if upstream accidentally duplicates it.
        $key = isset($run['id']) ? (string)$run['id'] : "index:$index";
        if (isset($seen[$key])) {
            continue;
        }
        $seen[$key] = true;
        $ts = strtotime((string)($run['created_at'] ?? ''));
        if ($ts === false || $ts <= $start48 || $ts > $end) {
            continue;
        }
        $recent = $ts > $start24;
        if (($run['status'] ?? null) === 'completed' &&
            ($run['conclusion'] ?? null) === 'success') {
            $success48++;
            if ($recent) {
                $success24++;
            }
        } else {
            $failed48++;
            if ($recent) {
                $failed24++;
            }
        }
    }
    $missing24 = max(0, $expected24 - $success24);
    $missing48 = max(0, $expected48 - $success48);
    $alerts = $warnings = [];
    if ($failed24 > 0) {
        $alerts[] = "$label : $failed24 exécution(s) programmée(s) non réussie(s) sur 24 h";
    } elseif ($failed48 > 0) {
        $warnings[] = "$label : $failed48 exécution(s) non réussie(s) sur 48 h (hors dernières 24 h)";
    }
    if ($missing24 >= 2 || $missing48 >= 2) {
        $alerts[] = "$label : déficit de cadence (24 h : $success24/$expected24 réussies ; 48 h : $success48/$expected48). Les créneaux individuels sont indéterminables.";
    } elseif ($missing24 > 0 || $missing48 > 0) {
        $warnings[] = "$label : cadence légèrement sous cible (24 h : $success24/$expected24 ; 48 h : $success48/$expected48) ; vérifier les retards GitHub.";
    }
    return [
        'alerts' => $alerts, 'warnings' => $warnings,
        'metrics' => ['expected_24h' => $expected24, 'success_24h' => $success24,
            'expected_48h' => $expected48, 'success_48h' => $success48,
            'failed_24h' => $failed24, 'failed_48h' => $failed48],
    ];
}

function watch_catalogue(string $label, array $spec, array $payload): array {
    [$path, $schemaKey, $version, $listKey, $minimum] = $spec;
    if (($payload[$schemaKey] ?? null) !== $version ||
        !isset($payload[$listKey]) || !is_array($payload[$listKey]) ||
        count($payload[$listKey]) < $minimum) {
        return ["$label : schéma/volume du JSON public anormal ($path)"];
    }
    return [];
}

function watch_check(callable $fetch, int $now): array {
    $alerts = [];
    $warnings = [];
    $workflowMetrics = [];
    $checks = 0;
    foreach (WATCH_WORKFLOWS as $label => $spec) {
        $url = 'https://api.github.com/repos/' . WATCH_REPO . '/actions/workflows/' . $spec[0] . '/runs?event=schedule&per_page=100';
        try {
            $report = watch_workflow_report($label, $spec, $fetch($url), $now);
            array_push($alerts, ...$report['alerts']);
            array_push($warnings, ...$report['warnings']);
            $workflowMetrics[$spec[0]] = $report['metrics'];
        } catch (Throwable $e) {
            $alerts[] = "$label : GitHub API inaccessible";
        }
        $checks++;
    }
    foreach (WATCH_CATALOGUES as $label => $spec) {
        $url = 'https://sarogal.github.io/Ondes-Catalogues/' . $spec[0];
        try {
            array_push($alerts, ...watch_catalogue($label, $spec, $fetch($url)));
        } catch (Throwable $e) {
            $alerts[] = "$label : JSON public inaccessible";
        }
        $checks++;
    }
    return ['ok' => count($alerts) === 0, 'checked_at_utc' => gmdate('c', $now),
        'checks' => $checks, 'alerts' => $alerts, 'warnings' => $warnings,
        'workflow_metrics' => $workflowMetrics,
        'cadence_method' => 'mature_24h_and_48h_counts_without_cron_attribution'];
}

function watch_expect(bool $condition): void {
    if (!$condition) {
        throw new RuntimeException('Échec d’un test du watchdog');
    }
}

function watch_self_test(): void {
    $now = strtotime('2026-11-18T09:14:00Z');
    $end = $now - 9 * 3600;
    $spec = ['example.yml', ['07:17', '10:17']];
    $slots = watch_window_slots($spec[1], $end - 2 * 86400, $end);
    watch_expect(count($slots) === 4);
    $runs = [];
    foreach ($slots as $index => $slot) {
        // Two delayed 8h and two on-time starts in a different order; no
        // inferred individual-cron identity, but all four runs succeeded.
        $runs[] = ['id' => $index + 1, 'event' => 'schedule',
            'created_at' => gmdate('c', $slot + ($index % 2 === 0 ? 8 * 3600 : 5 * 60)),
            'status' => 'completed', 'conclusion' => 'success'];
    }
    // Last delayed slot is still within the mature observation window.
    $good = watch_workflow_report('test', $spec, ['workflow_runs' => $runs], $now);
    watch_expect($good['alerts'] === []);
    watch_expect($good['warnings'] === []);
    watch_expect($good['metrics']['success_48h'] === 4);
    $single = $runs;
    array_pop($single);
    $one = watch_workflow_report('test', $spec, ['workflow_runs' => $single], $now);
    watch_expect($one['alerts'] === [] && count($one['warnings']) === 1);
    $double = $single;
    array_pop($double);
    $two = watch_workflow_report('test', $spec, ['workflow_runs' => $double], $now);
    watch_expect(count($two['alerts']) === 1);
    $broken = $runs;
    $broken[3]['conclusion'] = 'failure';
    $failed = watch_workflow_report('test', $spec, ['workflow_runs' => $broken], $now);
    watch_expect(count($failed['alerts']) === 1);
    $manual = $runs;
    foreach ($manual as &$run) {
        $run['event'] = 'workflow_dispatch';
    }
    unset($run);
    $ignored = watch_workflow_report('test', $spec, ['workflow_runs' => $manual], $now);
    watch_expect(count($ignored['alerts']) === 1);
    $duplicates = array_merge($runs, [$runs[0]]);
    $deduped = watch_workflow_report('test', $spec, ['workflow_runs' => $duplicates], $now);
    watch_expect($deduped['metrics']['success_48h'] === 4);
    watch_expect(watch_catalogue('Sorties', WATCH_CATALOGUES['Sorties'],
        ['version' => 3, 'events' => array_fill(0, 100, [])]) === []);
    watch_expect(count(watch_catalogue('Sorties', WATCH_CATALOGUES['Sorties'],
        ['version' => 3, 'events' => []])) === 1);
    $checked = watch_check(static function (string $url): array {
        if (str_contains($url, 'actions/workflows')) {
            return ['workflow_runs' => []];
        }
        return ['version' => 0];
    }, $now);
    watch_expect($checked['checks'] === 12 && $checked['ok'] === false);
    watch_expect(isset($checked['warnings'], $checked['workflow_metrics']));
    echo "Tests watchdog v2 : OK\n";
}

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) {
    if (in_array('--self-test', $argv ?? [], true)) {
        watch_self_test();
        exit(0);
    }
    if (PHP_SAPI !== 'cli') {
        // Infomaniak webcron: configure an untracked token (env or PHP local config).
        $local = __DIR__ . '/ondes-watchdog.local.php';
        $secret = is_file($local) ? require $local : getenv('ONDES_WATCHDOG_TOKEN');
        $supplied = $_GET['token'] ?? '';
        if (!is_string($secret) || strlen($secret) < 32 ||
            !is_string($supplied) || !hash_equals($secret, $supplied)) {
            http_response_code(403);
            exit('Interdit');
        }
        header('Content-Type: application/json; charset=utf-8');
    }
    $result = watch_check('watch_fetch', time());
    if (PHP_SAPI !== 'cli') {
        http_response_code($result['ok'] ? 200 : 503);
    }
    echo json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
    exit($result['ok'] ? 0 : 1);
}
