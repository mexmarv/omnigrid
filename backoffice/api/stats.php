<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();

$cutoff = microtime(true) - HEARTBEAT_TIMEOUT_S;
$stmt = $pdo->prepare('SELECT COUNT(*) AS n FROM providers WHERE last_heartbeat >= ?');
$stmt->execute([$cutoff]);
$online = (int)$stmt->fetch()['n'];

$jobs = $pdo->query(
    "SELECT COUNT(*) AS total, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done, " .
    "COALESCE(SUM(compute_seconds), 0) AS secs FROM jobs"
)->fetch();

$leaderboard = $pdo->query('SELECT name, credits FROM accounts ORDER BY credits DESC LIMIT 10')->fetchAll();

json_response([
    'providers_online' => $online,
    'jobs_total' => (int)($jobs['total'] ?? 0),
    'jobs_done' => (int)($jobs['done'] ?? 0),
    'compute_hours_donated' => round((float)($jobs['secs'] ?? 0) / 3600, 3),
    'leaderboard' => $leaderboard,
]);
