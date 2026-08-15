<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();
$account = require_auth($pdo);
$input = json_input();

$jobId = (int)($input['job_id'] ?? 0);
$job = require_owns_job_provider($pdo, $jobId, (int)$account['id']);
$computeSeconds = (float)($input['compute_seconds'] ?? 0);

$stmt = $pdo->prepare(
    "UPDATE jobs SET status='done', result_format=?, result_b64=?, compute_seconds=?, finished_at=? WHERE id=?"
);
$stmt->execute([
    $input['result_format'] ?? 'json', $input['result_b64'] ?? '', $computeSeconds, microtime(true), $jobId,
]);
$pdo->prepare('UPDATE providers SET busy = 0 WHERE id = ?')->execute([$job['provider_id']]);

$resourceWeight = (float)$job['cpu_limit'] + ((float)$job['ram_limit_mb'] / 1024);
$credits = $computeSeconds * $resourceWeight * CREDIT_RATE_PER_RESOURCE_SECOND;

$stmt = $pdo->prepare('SELECT account_id FROM providers WHERE id = ?');
$stmt->execute([$job['provider_id']]);
$providerAccountId = $stmt->fetch()['account_id'];

$pdo->prepare('UPDATE accounts SET credits = credits + ? WHERE id = ?')->execute([$credits, $providerAccountId]);
$pdo->prepare('UPDATE accounts SET credits = credits - ? WHERE id = ?')->execute([$credits, $job['consumer_account_id']]);

json_response(['ok' => true]);
