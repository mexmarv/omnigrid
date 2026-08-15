<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();
$account = require_auth($pdo);
$input = json_input();

$jobId = (int)($input['job_id'] ?? 0);
$job = require_owns_job_provider($pdo, $jobId, (int)$account['id']);

$stmt = $pdo->prepare("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?");
$stmt->execute([$input['error'] ?? '', microtime(true), $jobId]);

if ($job['provider_id'] !== null) {
    $pdo->prepare('UPDATE providers SET busy = 0 WHERE id = ?')->execute([$job['provider_id']]);
}

json_response(['ok' => true]);
