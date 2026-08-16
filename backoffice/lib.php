<?php
require_once __DIR__ . '/db.php';

const HEARTBEAT_TIMEOUT_S = 60;
const STARTING_CREDITS = 50.0;
const CREDIT_RATE_PER_RESOURCE_SECOND = 1.0;

function json_input(): array {
    $raw = file_get_contents('php://input');
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function json_response($data, int $status = 200): void {
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($data);
    exit;
}

function json_error(string $message, int $status): void {
    json_response(['detail' => $message], $status);
}

/** Some Apache/CGI shared-hosting setups strip the Authorization header by
 * default -- see the .htaccess in this folder for the standard fix. This
 * checks every place PHP might actually surface it. */
function get_bearer_token(): ?string {
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
    if ($header === null && function_exists('getallheaders')) {
        foreach (getallheaders() as $name => $value) {
            if (strtolower($name) === 'authorization') {
                $header = $value;
                break;
            }
        }
    }
    if ($header === null || !str_starts_with($header, 'Bearer ')) {
        return null;
    }
    return trim(substr($header, 7));
}

/** Non-exiting lookup (unlike require_auth) -- for callers with their own error format, e.g. mcp.php. */
function find_account_by_api_key(PDO $pdo, string $apiKey): array|false {
    $stmt = $pdo->prepare('SELECT * FROM accounts WHERE api_key_hash = ?');
    $stmt->execute([hash('sha256', $apiKey)]);
    return $stmt->fetch();
}

function require_auth(PDO $pdo): array {
    $token = get_bearer_token();
    if ($token === null) {
        json_error("Missing 'Authorization: Bearer <api_key>' header.", 401);
    }
    $account = find_account_by_api_key($pdo, $token);
    if ($account === false) {
        json_error('Invalid API key.', 401);
    }
    return $account;
}

/** Vision-language models this backoffice itself relays to directly, configured in
 * config.php's optional 'nvidia_models' key -- e.g.:
 *   'nvidia_models' => ['my-vision-model' => ['api_key' => 'nvapi-...', 'model_id' => '...']]
 * No separate always-on client process needed for these: the backoffice server
 * (already running 24/7) calls NVIDIA directly with the configured key when asked,
 * the same way a Python provider's vlm_infer handler would -- just without needing
 * a machine of your own to leave on. The key never leaves this server. */
function nvidia_hosted_models(): array {
    return omnigrid_config()['nvidia_models'] ?? [];
}

/** Relays a prompt (+ optional image) to NVIDIA's hosted NIM API and returns the
 * generated text. Mirrors client/handlers/nvidia_vlm.py's request shape exactly. */
function call_nvidia_vlm(string $modelId, string $apiKey, string $prompt,
                          ?string $imageB64, string $imageMime, int $maxTokens): string {
    $content = $prompt;
    if ($imageB64 !== null) {
        $content = [
            ['type' => 'text', 'text' => $prompt],
            ['type' => 'image_url', 'image_url' => ['url' => "data:$imageMime;base64,$imageB64"]],
        ];
    }
    $ch = curl_init('https://integrate.api.nvidia.com/v1/chat/completions');
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 60,
        CURLOPT_HTTPHEADER => ["Authorization: Bearer $apiKey", 'Content-Type: application/json'],
        CURLOPT_POSTFIELDS => json_encode([
            'model' => $modelId,
            'messages' => [['role' => 'user', 'content' => $content]],
            'max_tokens' => $maxTokens,
        ]),
    ]);
    $body = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curlError = curl_error($ch);
    // no curl_close() -- deprecated as of PHP 8.5, and has had no effect since PHP 8.0

    if ($body === false) {
        throw new RuntimeException("Could not reach NVIDIA's API: $curlError");
    }
    $data = json_decode($body, true);
    if ($status !== 200) {
        $detail = $data['error']['message'] ?? $body;
        throw new RuntimeException("NVIDIA API error ($status): $detail");
    }
    $content = $data['choices'][0]['message']['content'] ?? null;
    if ($content === null) {
        // Reasoning models can burn the whole max_tokens budget on their
        // internal reasoning before ever emitting a final answer, leaving
        // content null -- that used to violate this function's `: string`
        // return type and crash as an uncaught TypeError instead of a
        // readable error.
        $finishReason = $data['choices'][0]['finish_reason'] ?? 'unknown';
        throw new RuntimeException(
            "Model produced no final answer (finish_reason: $finishReason) -- " .
            "it likely hit max_tokens while still reasoning. Try again with a higher max_tokens."
        );
    }
    return $content;
}

/** task_type strings look like "llm_infer:<model-name>" or "vlm_infer:<model-name>" --
 * this pulls the model name out of either family, or null if it's neither. */
function model_name_from_task_type(string $taskType): ?string {
    foreach (['llm_infer:', 'vlm_infer:'] as $prefix) {
        if (str_starts_with($taskType, $prefix)) {
            return substr($taskType, strlen($prefix));
        }
    }
    return null;
}

/** Model names, deduped, from whichever providers are currently online. */
function list_hosted_models(PDO $pdo): array {
    $cutoff = microtime(true) - HEARTBEAT_TIMEOUT_S;
    $stmt = $pdo->prepare('SELECT task_types FROM providers WHERE last_heartbeat >= ?');
    $stmt->execute([$cutoff]);
    $models = [];
    foreach ($stmt->fetchAll() as $row) {
        foreach (explode(',', $row['task_types']) as $taskType) {
            $name = model_name_from_task_type($taskType);
            if ($name !== null) {
                $models[] = $name;
            }
        }
    }
    $models = array_merge($models, array_keys(nvidia_hosted_models()));
    $models = array_values(array_unique($models));
    sort($models);
    return $models;
}

/** Single source of truth for everything the dashboard shows -- used for both the
 * initial page render (index.php) and the live JS auto-refresh (api/stats.php),
 * so the two can never silently drift out of sync with each other. */
function dashboard_snapshot(PDO $pdo): array {
    $cutoff = microtime(true) - HEARTBEAT_TIMEOUT_S;
    $stmt = $pdo->prepare('SELECT cpu_cores, ram_mb, gpu_model, task_types FROM providers WHERE last_heartbeat >= ?');
    $stmt->execute([$cutoff]);
    $onlineProviders = $stmt->fetchAll();

    $totalCores = 0.0;
    $totalRamMb = 0;
    $gpuProviders = 0;
    $hostedModels = [];
    foreach ($onlineProviders as $p) {
        $totalCores += (float)$p['cpu_cores'];
        $totalRamMb += (int)$p['ram_mb'];
        if (!empty($p['gpu_model'])) {
            $gpuProviders++;
        }
        foreach (explode(',', $p['task_types']) as $taskType) {
            $name = model_name_from_task_type($taskType);
            if ($name !== null) {
                $hostedModels[] = $name;
            }
        }
    }
    $hostedModels = array_merge($hostedModels, array_keys(nvidia_hosted_models()));
    $hostedModels = array_values(array_unique($hostedModels));
    sort($hostedModels);

    $jobs = $pdo->query(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done, " .
        "COALESCE(SUM(compute_seconds), 0) AS secs FROM jobs"
    )->fetch();

    $leaderboard = $pdo->query('SELECT name, credits FROM accounts ORDER BY credits DESC LIMIT 10')->fetchAll();

    $recentActivity = $pdo->query(
        "SELECT task_type, compute_seconds, finished_at FROM jobs " .
        "WHERE status = 'done' ORDER BY finished_at DESC LIMIT 6"
    )->fetchAll();

    return [
        'providers_online' => count($onlineProviders),
        'total_cores' => $totalCores,
        'total_ram_mb' => $totalRamMb,
        'gpu_providers' => $gpuProviders,
        'hosted_models' => $hostedModels,
        'jobs_total' => (int)($jobs['total'] ?? 0),
        'jobs_done' => (int)($jobs['done'] ?? 0),
        'compute_hours_donated' => round((float)($jobs['secs'] ?? 0) / 3600, 3),
        'leaderboard' => array_map(fn($r) => ['name' => $r['name'], 'credits' => (float)$r['credits']], $leaderboard),
        'recent_activity' => array_map(fn($r) => [
            'task_type' => $r['task_type'],
            'compute_seconds' => (float)$r['compute_seconds'],
            'finished_at' => (float)$r['finished_at'],
        ], $recentActivity),
    ];
}

/** Inserts a queued job and blocks (server-side poll loop) until it's done/failed or
 * $maxWaitS elapses. Used by mcp.php, where a single HTTP request must synchronously
 * return a result -- there's no separate client-side poll step like client_sdk.py has. */
function submit_job_and_wait(PDO $pdo, int $accountId, string $taskType, string $payloadB64,
                              float $cpuLimit, int $ramLimitMb, int $timeoutS, int $maxWaitS): array {
    $stmt = $pdo->prepare(
        'INSERT INTO jobs (consumer_account_id, task_type, payload_format, payload_b64, cpu_limit, ' .
        'ram_limit_mb, gpu_required, timeout_s, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)'
    );
    $stmt->execute([$accountId, $taskType, 'json', $payloadB64, $cpuLimit, $ramLimitMb, $timeoutS, microtime(true)]);
    $jobId = (int)$pdo->lastInsertId();

    $deadline = microtime(true) + $maxWaitS;
    while (microtime(true) < $deadline) {
        usleep(300000); // 300ms
        $stmt = $pdo->prepare('SELECT * FROM jobs WHERE id = ?');
        $stmt->execute([$jobId]);
        $job = $stmt->fetch();
        if ($job['status'] === 'done' || $job['status'] === 'failed') {
            return $job;
        }
    }
    return ['status' => 'timeout', 'job_id' => $jobId, 'error' => "No provider completed this within {$maxWaitS}s."];
}

/** Flattens a nested PHP array into [flatFloatValues, shape]. */
function npy_flatten($data): array {
    if (!is_array($data)) {
        return [[(float)$data], []];
    }
    if (count($data) === 0) {
        return [[], [0]];
    }
    if (!is_array($data[0])) {
        return [array_map('floatval', $data), [count($data)]];
    }
    $flat = [];
    $innerShape = null;
    foreach ($data as $row) {
        [$rowFlat, $rowShape] = npy_flatten($row);
        $flat = array_merge($flat, $rowFlat);
        $innerShape = $rowShape;
    }
    return [$flat, array_merge([count($data)], $innerShape)];
}

/** Encodes a (possibly nested) PHP array as float64 .npy bytes -- byte-verified
 * against real numpy.load() for 2D, 1D, and scalar inputs. */
function npy_encode($data): string {
    [$flat, $shape] = npy_flatten($data);
    $shapeStr = count($shape) === 0 ? '()' : (count($shape) === 1 ? "({$shape[0]},)" : '(' . implode(', ', $shape) . ')');
    $header = "{'descr': '<f8', 'fortran_order': False, 'shape': $shapeStr, }";
    $prefixLen = 10 + strlen($header) + 1; // +1 for the trailing \n
    $padding = (64 - ($prefixLen % 64)) % 64;
    $header .= str_repeat(' ', $padding) . "\n";
    $out = "\x93NUMPY\x01\x00" . pack('v', strlen($header)) . $header;
    foreach ($flat as $v) {
        $out .= pack('e', $v);
    }
    return $out;
}

function npy_reshape(array $flat, array $shape) {
    if (count($shape) === 0) {
        return $flat[0];
    }
    if (count($shape) === 1) {
        return $flat;
    }
    $chunkSize = intdiv(count($flat), $shape[0]);
    $rest = array_slice($shape, 1);
    $out = [];
    for ($i = 0; $i < $shape[0]; $i++) {
        $out[] = npy_reshape(array_slice($flat, $i * $chunkSize, $chunkSize), $rest);
    }
    return $out;
}

/** Decodes float64 .npy bytes back into a (possibly nested) PHP array or scalar --
 * byte-verified against genuine numpy-written files. */
function npy_decode(string $bytes) {
    if (substr($bytes, 0, 6) !== "\x93NUMPY") {
        throw new RuntimeException('Not a valid .npy file.');
    }
    $headerLen = unpack('v', substr($bytes, 8, 2))[1];
    $header = substr($bytes, 10, $headerLen);
    $dataOffset = 10 + $headerLen;

    if (!preg_match("/'descr':\s*'([^']+)'/", $header, $m) || $m[1] !== '<f8') {
        throw new RuntimeException("Unsupported .npy dtype: $header");
    }
    preg_match("/'shape':\s*\(([^)]*)\)/", $header, $sm);
    $shapeStr = trim($sm[1]);
    $shape = $shapeStr === '' ? [] : array_map('intval', array_filter(array_map('trim', explode(',', $shapeStr)), fn($s) => $s !== ''));

    $count = $shape === [] ? 1 : array_product($shape);
    $values = array_values(unpack('e' . $count, substr($bytes, $dataOffset, $count * 8)));

    return npy_reshape($values, $shape);
}

/** Returns ['account_id' => int, 'api_key' => string]. Throws RuntimeException on duplicate name. */
function register_account(PDO $pdo, string $name, string $email): array {
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        throw new RuntimeException('That email address looks invalid.');
    }
    $apiKey = bin2hex(random_bytes(32));
    $hash = hash('sha256', $apiKey);
    try {
        $stmt = $pdo->prepare(
            'INSERT INTO accounts (name, email, api_key_hash, credits, created_at) VALUES (?, ?, ?, ?, ?)'
        );
        $stmt->execute([$name, $email, $hash, STARTING_CREDITS, microtime(true)]);
    } catch (PDOException $e) {
        throw new RuntimeException("Account name '$name' is already registered.");
    }
    return ['account_id' => (int)$pdo->lastInsertId(), 'api_key' => $apiKey];
}

const RESET_TOKEN_TTL_S = 3600; // 1 hour

/** No password to reset -- this emails a one-time link that lets you reissue your
 * API key or delete your account. Always call this the same way whether or not
 * the name/email actually matched, so responses can't be used to enumerate accounts. */
function request_password_reset(PDO $pdo, string $name, string $email, string $baseUrl): void {
    $stmt = $pdo->prepare('SELECT id FROM accounts WHERE name = ? AND email = ?');
    $stmt->execute([$name, $email]);
    $account = $stmt->fetch();
    if ($account === false) {
        return; // silently no-op -- caller shows the same "check your email" message either way
    }

    $token = bin2hex(random_bytes(32));
    $stmt = $pdo->prepare('UPDATE accounts SET reset_token_hash = ?, reset_expires = ? WHERE id = ?');
    $stmt->execute([hash('sha256', $token), microtime(true) + RESET_TOKEN_TTL_S, $account['id']]);

    $link = "$baseUrl/reset.php?token=$token";
    $body = "Someone (hopefully you) asked to manage the Omnigrid account '$name'.\n\n" .
        "Reset your API key or delete the account here (link expires in 1 hour):\n$link\n\n" .
        "If this wasn't you, ignore this email -- nothing happens without clicking the link.";
    $from = omnigrid_config()['mail_from'] ?? ('no-reply@' . parse_url($baseUrl, PHP_URL_HOST));
    @mail($email, 'Omnigrid account access', $body, "From: $from");
}

/** Returns the account row for a valid, unexpired reset token, or null. */
function find_account_by_reset_token(PDO $pdo, string $token): ?array {
    $stmt = $pdo->prepare('SELECT * FROM accounts WHERE reset_token_hash = ?');
    $stmt->execute([hash('sha256', $token)]);
    $account = $stmt->fetch();
    if ($account === false || (float)$account['reset_expires'] < microtime(true)) {
        return null;
    }
    return $account;
}

/** Issues a fresh API key (invalidating the old one) and clears the reset token. */
function reissue_api_key(PDO $pdo, int $accountId): string {
    $apiKey = bin2hex(random_bytes(32));
    $stmt = $pdo->prepare(
        'UPDATE accounts SET api_key_hash = ?, reset_token_hash = NULL, reset_expires = NULL WHERE id = ?'
    );
    $stmt->execute([hash('sha256', $apiKey), $accountId]);
    return $apiKey;
}

/** Deletes the account and any providers it registered. Jobs are left as historical
 * records (their consumer_account_id/provider_id just won't resolve to anything anymore). */
function delete_account(PDO $pdo, int $accountId): void {
    $pdo->prepare('DELETE FROM providers WHERE account_id = ?')->execute([$accountId]);
    $pdo->prepare('DELETE FROM accounts WHERE id = ?')->execute([$accountId]);
}

/** Verifies job_id exists and is assigned to a provider owned by $accountId. */
function require_owns_job_provider(PDO $pdo, int $jobId, int $accountId): array {
    $stmt = $pdo->prepare('SELECT * FROM jobs WHERE id = ?');
    $stmt->execute([$jobId]);
    $job = $stmt->fetch();
    if ($job === false) {
        json_error('Unknown job.', 404);
    }

    $stmt = $pdo->prepare('SELECT account_id FROM providers WHERE id = ?');
    $stmt->execute([$job['provider_id']]);
    $provider = $stmt->fetch();
    if ($provider === false || (int)$provider['account_id'] !== $accountId) {
        json_error("This job isn't assigned to one of your providers.", 403);
    }
    return $job;
}
