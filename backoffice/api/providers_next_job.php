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

// Claim atomically: two providers hosting the same model can poll at nearly
// the same instant, both see the same queued job, and both try to take it.
// The UPDATE's own WHERE status='queued' makes only one of them actually win --
// whoever loses just moves on to the next candidate instead of double-running it.
$claim = $pdo->prepare("UPDATE jobs SET status='assigned', provider_id=? WHERE id=? AND status='queued'");
$job = null;
foreach ($candidates as $candidate) {
    if (!in_array($candidate['task_type'], $supported, true)) {
        continue;
    }
    $claim->execute([$provider['id'], $candidate['id']]);
    if ($claim->rowCount() === 1) {
        $job = $candidate;
        break;
    }
}

if ($job === null) {
    http_response_code(204);
    exit; // HTTP 204 must not carry a body
}

$pdo->prepare('UPDATE providers SET busy = 1 WHERE id = ?')->execute([$provider['id']]);

$stmt = $pdo->prepare('SELECT * FROM jobs WHERE id = ?');
$stmt->execute([$job['id']]);
json_response($stmt->fetch());
