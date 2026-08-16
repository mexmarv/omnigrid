<?php
/**
 * Upload an image directly (multipart/form-data) instead of base64-encoding
 * it yourself and pasting/embedding that string in a JSON body or MCP tool
 * call. This endpoint reads the uploaded file and base64-encodes it here,
 * server-side, in this request's own memory -- then queues the exact same
 * vlm_infer job jobs_submit.php would, just with a friendlier front door
 * for image payloads specifically. No new job schema, no new security
 * boundary: still data in, fixed handler on the provider side, same as
 * every other task_type.
 *
 * multipart/form-data fields:
 *   image       -- the image file (required)
 *   task_type   -- e.g. "vlm_infer:moondream-m4" (required, must start with "vlm_infer:")
 *   prompt      -- text prompt (required)
 *   max_tokens  -- optional int, default 512
 */
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();
$account = require_auth($pdo);

const MAX_UPLOAD_BYTES = 8 * 1024 * 1024; // 8MB -- generous for a single image

$taskType = $_POST['task_type'] ?? '';
if (!str_starts_with($taskType, 'vlm_infer:')) {
    json_error("task_type must start with 'vlm_infer:' -- this endpoint is for image jobs only.", 400);
}

$prompt = $_POST['prompt'] ?? '';
if ($prompt === '') {
    json_error('prompt is required.', 400);
}

if (!isset($_FILES['image']) || $_FILES['image']['error'] !== UPLOAD_ERR_OK) {
    json_error('image file upload is required (multipart/form-data field "image").', 400);
}

$tmpPath = $_FILES['image']['tmp_name'];
$size = filesize($tmpPath);
if ($size === false || $size > MAX_UPLOAD_BYTES) {
    json_error('image must be a valid file under ' . (MAX_UPLOAD_BYTES / 1024 / 1024) . 'MB.', 400);
}

$mime = mime_content_type($tmpPath);
if ($mime === false || !str_starts_with($mime, 'image/')) {
    json_error('Uploaded file does not look like an image.', 400);
}

// The one line that matters: converted to base64 here, in this request's
// own memory, server-side -- the caller only ever sent raw file bytes.
$imageB64 = base64_encode(file_get_contents($tmpPath));

$payload = [
    'prompt' => $prompt,
    'image_b64' => $imageB64,
    'image_mime' => $mime,
    'max_tokens' => (int)($_POST['max_tokens'] ?? 512),
];
$payloadB64 = base64_encode(json_encode($payload));

$stmt = $pdo->prepare(
    'INSERT INTO jobs (consumer_account_id, task_type, payload_format, payload_b64, cpu_limit, ' .
    'ram_limit_mb, gpu_required, timeout_s, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)'
);
$stmt->execute([
    $account['id'], $taskType, 'json', $payloadB64, 1.0, 512, 60, microtime(true),
]);
json_response(['job_id' => (int)$pdo->lastInsertId()]);
