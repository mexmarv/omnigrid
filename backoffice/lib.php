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

function require_auth(PDO $pdo): array {
    $token = get_bearer_token();
    if ($token === null) {
        json_error("Missing 'Authorization: Bearer <api_key>' header.", 401);
    }
    $hash = hash('sha256', $token);
    $stmt = $pdo->prepare('SELECT * FROM accounts WHERE api_key_hash = ?');
    $stmt->execute([$hash]);
    $account = $stmt->fetch();
    if ($account === false) {
        json_error('Invalid API key.', 401);
    }
    return $account;
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
