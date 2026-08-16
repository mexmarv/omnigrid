<?php
/**
 * MCP server, hosted -- no local install, no Python, nothing to download.
 * Point Omnigent's tools: config at this URL and you're done.
 *
 * Implements the subset of MCP's Streamable HTTP transport needed for a
 * stateless, tools-only server: JSON-RPC 2.0 over POST, one request in,
 * one response out, no session id, no SSE. Verified against the real
 * `mcp` Python client library (both this hand-rolled version and the
 * reference FastMCP server were exercised the same way) -- not just
 * "looks like the spec", actually interoperates.
 *
 * Same security model as everywhere else in this project: only
 * JSON/data crosses this endpoint, never code. list_models needs no
 * auth; the rest read the caller's API key from the Authorization
 * header (set via Omnigent's `headers:` config) to know which account
 * to credit/debit, and to check job ownership.
 *
 * Long jobs, without trusting a host's execution-time limit: a fixed
 * 20-30s wait breaks down the moment a model or provider is slow, and
 * shared hosts differ wildly in what they'll actually let a script run
 * for. So no single request here ever blocks longer than
 * INITIAL_WAIT_S/POLL_WAIT_S (a few seconds, safely under even strict
 * hosts) -- offload_* returns a real result immediately for fast jobs,
 * or a job_id + "still running" for slow ones, and the agent is told to
 * call check_job_result(job_id) again, which itself waits briefly and
 * repeats the same pattern. Total wait is unbounded; each individual
 * HTTP call stays short no matter what the host allows.
 */

require_once __DIR__ . '/lib.php';
$pdo = omnigrid_db();

const INITIAL_WAIT_S = 10;
const POLL_WAIT_S = 10;
set_time_limit(30);

header('Content-Type: application/json');

$raw = file_get_contents('php://input');
$req = json_decode($raw, true);

function rpc_result($id, array $result): void {
    echo json_encode(['jsonrpc' => '2.0', 'id' => $id, 'result' => $result]);
    exit;
}

function rpc_error($id, int $code, string $message): void {
    echo json_encode(['jsonrpc' => '2.0', 'id' => $id, 'error' => ['code' => $code, 'message' => $message]]);
    exit;
}

function tool_error($id, string $message): void {
    rpc_result($id, ['content' => [['type' => 'text', 'text' => $message]], 'isError' => true]);
}

function tool_text_result($id, string $text, $structured = null): void {
    $result = ['content' => [['type' => 'text', 'text' => $text]], 'isError' => false];
    if ($structured !== null) {
        $result['structuredContent'] = $structured;
    }
    rpc_result($id, $result);
}

function tool_pending_result($id, int $jobId): void {
    tool_text_result(
        $id,
        "Still running as job #$jobId -- not unusual for a busy or slow community provider. " .
        "Call check_job_result with job_id=$jobId to keep waiting for it; it's safe to call " .
        "again as many times as needed.",
        ['status' => 'queued', 'job_id' => $jobId]
    );
}

/** Renders a finished job's result the same way regardless of which tool call it came from. */
function tool_result_from_job($id, array $job): void {
    if ($job['task_type'] === 'tensor_op') {
        $result = json_decode(base64_decode($job['result_b64']), true);
        $value = npy_decode(base64_decode($result['result_npy_b64']));
        tool_text_result($id, json_encode($value), ['status' => 'done', 'result' => $value]);
    } else { // llm_infer:<model>
        $result = json_decode(base64_decode($job['result_b64']), true);
        tool_text_result($id, $result['text'], ['status' => 'done', 'text' => $result['text']]);
    }
}

if (!is_array($req) || !isset($req['method'])) {
    http_response_code(400);
    rpc_error(null, -32600, 'Invalid Request');
}

$method = $req['method'];
$id = $req['id'] ?? null;
$params = $req['params'] ?? [];

switch ($method) {
    case 'initialize':
        rpc_result($id, [
            'protocolVersion' => $params['protocolVersion'] ?? '2025-06-18',
            'capabilities' => ['tools' => ['listChanged' => false]],
            'serverInfo' => ['name' => 'omnigrid', 'version' => '1.0'],
        ]);
        break;

    case 'notifications/initialized':
        http_response_code(202);
        exit;

    case 'tools/list':
        rpc_result($id, ['tools' => [
            [
                'name' => 'list_models',
                'description' => 'List LLM models currently hosted by online providers on the Omnigrid network.',
                'inputSchema' => ['type' => 'object', 'properties' => new stdClass()],
            ],
            [
                'name' => 'offload_llm_generate',
                'description' => 'Generate text using a community-hosted open model instead of your own ' .
                    'configured model. Call list_models first to see what is currently available. If the ' .
                    'provider is slow, this returns a job_id instead of the text -- call check_job_result ' .
                    'with it to keep waiting.',
                'inputSchema' => [
                    'type' => 'object',
                    'properties' => [
                        'prompt' => ['type' => 'string'],
                        'model_name' => ['type' => 'string'],
                        'max_tokens' => ['type' => 'integer', 'default' => 256],
                        'temperature' => ['type' => 'number', 'default' => 0.7],
                        'system' => ['type' => 'string'],
                    ],
                    'required' => ['prompt', 'model_name'],
                ],
            ],
            [
                'name' => 'offload_vlm_generate',
                'description' => 'Generate text from a prompt and an optional image using a community-hosted ' .
                    'vision-language model (e.g. a free NVIDIA-hosted model relayed through a provider\'s own ' .
                    'API key). Call list_models first to see what is currently available. If the provider is ' .
                    'slow, this returns a job_id instead of the text -- call check_job_result with it to keep waiting.',
                'inputSchema' => [
                    'type' => 'object',
                    'properties' => [
                        'prompt' => ['type' => 'string'],
                        'model_name' => ['type' => 'string'],
                        'image_b64' => ['type' => 'string', 'description' => 'optional base64-encoded image'],
                        'image_mime' => ['type' => 'string', 'default' => 'image/jpeg'],
                        'max_tokens' => ['type' => 'integer', 'default' => 512],
                    ],
                    'required' => ['prompt', 'model_name'],
                ],
            ],
            [
                'name' => 'offload_tensor_op',
                'description' => 'Run a numeric tensor operation (matmul/add/multiply/relu/sum/mean) on the ' .
                    'network. If the provider is slow, this returns a job_id instead of the result -- call ' .
                    'check_job_result with it to keep waiting.',
                'inputSchema' => [
                    'type' => 'object',
                    'properties' => [
                        'op' => ['type' => 'string'],
                        'a' => ['type' => 'array'],
                        'b' => ['type' => 'array'],
                    ],
                    'required' => ['op', 'a'],
                ],
            ],
            [
                'name' => 'check_job_result',
                'description' => 'Check on (and keep waiting briefly for) a job_id previously returned by ' .
                    'offload_llm_generate or offload_tensor_op as still running. Safe to call repeatedly.',
                'inputSchema' => [
                    'type' => 'object',
                    'properties' => ['job_id' => ['type' => 'integer']],
                    'required' => ['job_id'],
                ],
            ],
        ]]);
        break;

    case 'tools/call':
        $name = $params['name'] ?? '';
        $args = $params['arguments'] ?? [];

        if ($name === 'list_models') {
            $models = list_hosted_models($pdo);
            tool_text_result($id, empty($models) ? 'No models currently hosted.' : implode(', ', $models),
                              ['result' => $models]);
        }

        // Every other tool spends credits or reveals job data, so it needs to know who's calling.
        $token = get_bearer_token();
        $account = $token !== null ? find_account_by_api_key($pdo, $token) : false;
        if ($account === false) {
            tool_error($id, "Missing or invalid API key. Configure 'headers: {Authorization: \"Bearer " .
                "<your-api-key>\"}' on this tool -- get a key at /register.php.");
        }

        if ($name === 'offload_llm_generate') {
            $payload = [
                'prompt' => $args['prompt'] ?? '',
                'max_tokens' => (int)($args['max_tokens'] ?? 256),
                'temperature' => (float)($args['temperature'] ?? 0.7),
            ];
            if (!empty($args['system'])) {
                $payload['system'] = $args['system'];
            }
            $payloadB64 = base64_encode(json_encode($payload));
            $modelName = $args['model_name'] ?? '';
            $job = submit_job_and_wait($pdo, (int)$account['id'], "llm_infer:$modelName", $payloadB64,
                                        1.0, 1024, 300, INITIAL_WAIT_S);
            if ($job['status'] === 'done') {
                tool_result_from_job($id, $job);
            } elseif ($job['status'] === 'timeout') {
                tool_pending_result($id, $job['job_id']);
            } else {
                tool_error($id, $job['error'] ?? 'Job failed.');
            }
        } elseif ($name === 'offload_vlm_generate') {
            $payload = [
                'prompt' => $args['prompt'] ?? '',
                'max_tokens' => (int)($args['max_tokens'] ?? 512),
            ];
            if (!empty($args['image_b64'])) {
                $payload['image_b64'] = $args['image_b64'];
                $payload['image_mime'] = $args['image_mime'] ?? 'image/jpeg';
            }
            $payloadB64 = base64_encode(json_encode($payload));
            $modelName = $args['model_name'] ?? '';
            $job = submit_job_and_wait($pdo, (int)$account['id'], "vlm_infer:$modelName", $payloadB64,
                                        1.0, 512, 60, INITIAL_WAIT_S);
            if ($job['status'] === 'done') {
                tool_result_from_job($id, $job);
            } elseif ($job['status'] === 'timeout') {
                tool_pending_result($id, $job['job_id']);
            } else {
                tool_error($id, $job['error'] ?? 'Job failed.');
            }
        } elseif ($name === 'offload_tensor_op') {
            $payload = ['op' => $args['op'] ?? '', 'a_npy_b64' => base64_encode(npy_encode($args['a'] ?? []))];
            if (isset($args['b'])) {
                $payload['b_npy_b64'] = base64_encode(npy_encode($args['b']));
            }
            $payloadB64 = base64_encode(json_encode($payload));
            $job = submit_job_and_wait($pdo, (int)$account['id'], 'tensor_op', $payloadB64,
                                        1.0, 512, 60, INITIAL_WAIT_S);
            if ($job['status'] === 'done') {
                tool_result_from_job($id, $job);
            } elseif ($job['status'] === 'timeout') {
                tool_pending_result($id, $job['job_id']);
            } else {
                tool_error($id, $job['error'] ?? 'Job failed.');
            }
        } elseif ($name === 'check_job_result') {
            $jobId = (int)($args['job_id'] ?? 0);
            $stmt = $pdo->prepare('SELECT * FROM jobs WHERE id = ?');
            $stmt->execute([$jobId]);
            $job = $stmt->fetch();
            if ($job === false) {
                tool_error($id, "Unknown job_id $jobId.");
            } elseif ((int)$job['consumer_account_id'] !== (int)$account['id']) {
                tool_error($id, "job_id $jobId isn't one of your own jobs.");
            } elseif ($job['status'] === 'done') {
                tool_result_from_job($id, $job);
            } elseif ($job['status'] === 'failed') {
                tool_error($id, $job['error'] ?? 'Job failed.');
            } else {
                // still queued/assigned -- wait a little more before answering, same pattern as the
                // initial call, so the agent doesn't need its own delay between polls.
                $deadline = microtime(true) + POLL_WAIT_S;
                while (microtime(true) < $deadline) {
                    usleep(300000);
                    $stmt = $pdo->prepare('SELECT * FROM jobs WHERE id = ?');
                    $stmt->execute([$jobId]);
                    $job = $stmt->fetch();
                    if ($job['status'] === 'done') {
                        tool_result_from_job($id, $job);
                    }
                    if ($job['status'] === 'failed') {
                        tool_error($id, $job['error'] ?? 'Job failed.');
                    }
                }
                tool_pending_result($id, $jobId);
            }
        } else {
            rpc_error($id, -32602, "Unknown tool: $name");
        }
        break;

    default:
        rpc_error($id, -32601, "Method not found: $method");
}
