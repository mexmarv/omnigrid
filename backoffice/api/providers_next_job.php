<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();
$account = require_auth($pdo);

$providerId = (int)($_GET['provider_id'] ?? 0);
$stmt = $pdo->prepare('SELECT * FROM providers WHERE id = ?');
$stmt->execute([$providerId]);
$provider = $stmt->fetch();
if ($provider === false) {
    json_error('Unknown provider.', 404);
}
if ((int)$provider['account_id'] !== (int)$account['id']) {
    json_error('That provider_id belongs to a different account.', 403);
}

$gpuClause = $provider['gpu_model'] ? '' : 'AND gpu_required = 0';
$stmt = $pdo->prepare(
    "SELECT * FROM jobs WHERE status = 'queued' AND cpu_limit <= ? AND ram_limit_mb <= ? $gpuClause ORDER BY created_at ASC"
);
$stmt->execute([$provider['cpu_cores'], $provider['ram_mb']]);
$candidates = $stmt->fetchAll();

$supported = explode(',', $provider['task_types']);
$job = null;
foreach ($candidates as $candidate) {
    if (in_array($candidate['task_type'], $supported, true)) {
        $job = $candidate;
        break;
    }
}

if ($job === null) {
    http_response_code(204);
    exit; // HTTP 204 must not carry a body
}

$stmt = $pdo->prepare("UPDATE jobs SET status='assigned', provider_id=? WHERE id=?");
$stmt->execute([$provider['id'], $job['id']]);
$pdo->prepare('UPDATE providers SET busy = 1 WHERE id = ?')->execute([$provider['id']]);

$stmt = $pdo->prepare('SELECT * FROM jobs WHERE id = ?');
$stmt->execute([$job['id']]);
json_response($stmt->fetch());
