<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();

$cutoff = microtime(true) - HEARTBEAT_TIMEOUT_S;
$stmt = $pdo->prepare('SELECT * FROM providers WHERE last_heartbeat >= ? AND busy = 0');
$stmt->execute([$cutoff]);
json_response($stmt->fetchAll());
