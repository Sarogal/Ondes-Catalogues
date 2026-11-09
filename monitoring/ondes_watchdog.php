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

function watch_slots(array $hours, int $now): array {
    // GitHub cron runs can begin hours late; allow nine hours before accusing a missed passage.
    $earliest = $now - 33 * 3600;
    $latest = $now - 9 * 3600;
    $day = (int)(floor($earliest / 86400) * 86400);
    $slots = [];
    while ($day <= $latest) {
        foreach ($hours as $hhmm) {
            [$hour, $minute] = array_map('intval', explode(':', $hhmm));
            $slot = $day + $hour * 3600 + $minute * 60;
            if ($slot >= $earliest && $slot <= $latest) {
                $slots[] = $slot;
            }
        }
        $day += 86400;
    }
    sort($slots);
    return $slots;
}

function watch_workflow(string $label, array $spec, array $payload, int $now): array {
    if (!isset($payload['workflow_runs']) || !is_array($payload['workflow_runs'])) {
        return ["$label : réponse API invalide"];
    }
    $runs = [];
    foreach ($payload['workflow_runs'] as $run) {
        if (!is_array($run) || ($run['event'] ?? null) !== 'schedule') {
            continue;
        }
        $ts = strtotime((string)($run['created_at'] ?? ''));
        if ($ts !== false && $ts <= $now) {
            $runs[] = ['ts' => $ts, 'status' => $run['status'] ?? '', 'conclusion' => $run['conclusion'] ?? ''];
        }
    }
    $used = [];
    $alerts = [];
    foreach (watch_slots($spec[1], $now) as $slot) {
        $selected = null;
        // A single run cannot validate several scheduled slots.
        foreach ($runs as $index => $run) {
            if (isset($used[$index]) || $run['ts'] < $slot - 120 || $run['ts'] > $slot + 32400) {
                continue;
            }
            if ($selected === null || $run['ts'] < $runs[$selected]['ts']) {
                $selected = $index;
            }
        }
        $time = gmdate('d/m H:i', $slot) . ' UTC';
        if ($selected === null) {
            $alerts[] = "$label : passage programmé absent ($time)";
        } else {
            $used[$selected] = true;
            if ($runs[$selected]['status'] !== 'completed' || $runs[$selected]['conclusion'] !== 'success') {
                $alerts[] = "$label : passage non réussi ($time)";
            }
        }
    }
    return $alerts;
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
    $checks = 0;
    foreach (WATCH_WORKFLOWS as $label => $spec) {
        $url = 'https://api.github.com/repos/' . WATCH_REPO . '/actions/workflows/' . $spec[0] . '/runs?event=schedule&per_page=100';
        try {
            array_push($alerts, ...watch_workflow($label, $spec, $fetch($url), $now));
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
        'checks' => $checks, 'alerts' => $alerts];
}

function watch_expect(bool $condition): void {
    if (!$condition) {
        throw new RuntimeException('Échec d’un test du watchdog');
    }
}

function watch_self_test(): void {
    $now = strtotime('2026-11-07T20:30:00Z');
    $spec = ['example.yml', ['07:17', '10:17']];
    $slots = watch_slots($spec[1], $now);
    watch_expect(count($slots) === 2); // yesterday's 07:17 and 10:17 are mature after nine hours.
    $runs = [];
    foreach ($slots as $slot) {
        $runs[] = ['event' => 'schedule', 'created_at' => gmdate('c', $slot + 5 * 3600),
            'status' => 'completed', 'conclusion' => 'success'];
    }
    watch_expect(watch_workflow('test', $spec, ['workflow_runs' => $runs], $now) === []);
    watch_expect(count(watch_workflow('test', $spec, ['workflow_runs' => [$runs[0]]], $now)) === 1);
    $runs[1]['conclusion'] = 'failure';
    watch_expect(count(watch_workflow('test', $spec, ['workflow_runs' => $runs], $now)) === 1);
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
    echo "Tests watchdog : OK\n";
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
