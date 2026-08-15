<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();

$input = json_input();
$name = trim($input['name'] ?? '');
if ($name === '') {
    json_error('name is required.', 400);
}

try {
    $result = register_account($pdo, $name);
} catch (RuntimeException $e) {
    json_error($e->getMessage(), 409);
}

json_response($result);
