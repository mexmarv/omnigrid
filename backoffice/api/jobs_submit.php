<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();
$account = require_auth($pdo);
$input = json_input();

$allowedFormats = ['json', 'npy', 'onnx'];
$payloadFormat = $input['payload_format'] ?? '';
if (!in_array($payloadFormat, $allowedFormats, true)) {
    json_error(
        'payload_format must be one of ' . implode(', ', $allowedFormats) .
        ' -- raw code/pickle/commands are never accepted.',
        400
    );
}

$stmt = $pdo->prepare(
    'INSERT INTO jobs (consumer_account_id, task_type, payload_format, payload_b64, cpu_limit, ' .
    'ram_limit_mb, gpu_required, timeout_s, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
);
$stmt->execute([
    $account['id'],
    $input['task_type'] ?? '',
    $payloadFormat,
    $input['payload_b64'] ?? '',
    (float)($input['cpu_limit'] ?? 1.0),
    (int)($input['ram_limit_mb'] ?? 512),
    !empty($input['gpu_required']) ? 1 : 0,
    (int)($input['timeout_s'] ?? 30),
    microtime(true),
]);
json_response(['job_id' => (int)$pdo->lastInsertId()]);
