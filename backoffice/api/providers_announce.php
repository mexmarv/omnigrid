<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();
$account = require_auth($pdo);
$input = json_input();

$providerId = isset($input['provider_id']) ? (int)$input['provider_id'] : null;
$cpuCores = (float)($input['cpu_cores'] ?? 0);
$ramMb = (int)($input['ram_mb'] ?? 0);
$gpuModel = $input['gpu_model'] ?? null;
$gpuVramMb = isset($input['gpu_vram_mb']) ? (int)$input['gpu_vram_mb'] : null;
$taskTypes = $input['task_types'] ?? [];
if (!is_array($taskTypes) || count($taskTypes) === 0) {
    json_error('task_types must be a non-empty array.', 400);
}
$taskTypesCsv = implode(',', $taskTypes);
$now = microtime(true);

if ($providerId !== null) {
    $stmt = $pdo->prepare('SELECT account_id FROM providers WHERE id = ?');
    $stmt->execute([$providerId]);
    $existing = $stmt->fetch();
    if ($existing === false) {
        json_error('Unknown provider_id.', 404);
    }
    if ((int)$existing['account_id'] !== (int)$account['id']) {
        json_error('That provider_id belongs to a different account.', 403);
    }
    $stmt = $pdo->prepare('UPDATE providers SET cpu_cores=?, ram_mb=?, gpu_model=?, gpu_vram_mb=?, task_types=?, last_heartbeat=? WHERE id=?');
    $stmt->execute([$cpuCores, $ramMb, $gpuModel, $gpuVramMb, $taskTypesCsv, $now, $providerId]);
    json_response(['provider_id' => $providerId]);
}

$stmt = $pdo->prepare('INSERT INTO providers (account_id, cpu_cores, ram_mb, gpu_model, gpu_vram_mb, task_types, last_heartbeat) VALUES (?, ?, ?, ?, ?, ?, ?)');
$stmt->execute([$account['id'], $cpuCores, $ramMb, $gpuModel, $gpuVramMb, $taskTypesCsv, $now]);
json_response(['provider_id' => (int)$pdo->lastInsertId()]);
