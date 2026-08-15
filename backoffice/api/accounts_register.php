<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();

$input = json_input();
$name = trim($input['name'] ?? '');
if ($name === '') {
    json_error('name is required.', 400);
}

$apiKey = bin2hex(random_bytes(32));
$hash = hash('sha256', $apiKey);

try {
    $stmt = $pdo->prepare('INSERT INTO accounts (name, api_key_hash, credits, created_at) VALUES (?, ?, ?, ?)');
    $stmt->execute([$name, $hash, STARTING_CREDITS, microtime(true)]);
} catch (PDOException $e) {
    json_error("Account name '$name' is already registered.", 409);
}

json_response(['account_id' => (int)$pdo->lastInsertId(), 'api_key' => $apiKey]);
