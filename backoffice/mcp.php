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
 * auth; offload_llm_generate/offload_tensor_op read the caller's API
 * key from the Authorization header (set via Omnigent's `headers:`
 * config) to know which account to credit/debit.
 */

require_once __DIR__ . '/lib.php';
$pdo = omnigrid_db();

// offload_* tools block synchronously waiting for a provider to finish --
// shared hosting typically caps script execution around 30s regardless of
// this call, so keep the internal wait safely under that rather than
// trusting php.ini's default (verified locally: the default killed a 90s
// wait mid-poll). MAX_WAIT_S below is the hard ceiling this endpoint uses.
const MAX_WAIT_S = 20;
set_time_limit(MAX_WAIT_S + 10);

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
                    'configured model. Call list_models first to see what is currently available.',
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
                'name' => 'offload_tensor_op',
                'description' => 'Run a numeric tensor operation (matmul/add/multiply/relu/sum/mean) on the network.',
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

        // The remaining tools spend credits, so they need to know who's calling.
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
                                        1.0, 1024, MAX_WAIT_S, MAX_WAIT_S);
            if ($job['status'] === 'done') {
                $result = json_decode(base64_decode($job['result_b64']), true);
                tool_text_result($id, $result['text']);
            } elseif ($job['status'] === 'timeout') {
                tool_error($id, "No provider finished job #{$job['job_id']} within " . MAX_WAIT_S .
                    "s -- it may still complete; the community provider could be slow or busy right now.");
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
                                        1.0, 512, MAX_WAIT_S, MAX_WAIT_S);
            if ($job['status'] === 'done') {
                $result = json_decode(base64_decode($job['result_b64']), true);
                $value = npy_decode(base64_decode($result['result_npy_b64']));
                tool_text_result($id, json_encode($value), ['result' => $value]);
            } elseif ($job['status'] === 'timeout') {
                tool_error($id, "No provider finished job #{$job['job_id']} within " . MAX_WAIT_S .
                    "s -- try again shortly.");
            } else {
                tool_error($id, $job['error'] ?? 'Job failed.');
            }
        } else {
            rpc_error($id, -32602, "Unknown tool: $name");
        }
        break;

    default:
        rpc_error($id, -32601, "Method not found: $method");
}
