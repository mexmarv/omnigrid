<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();

$input = json_input();
$name = trim($input['name'] ?? '');
$email = trim($input['email'] ?? '');
if ($name === '') {
    json_error('name is required.', 400);
}
if ($email === '') {
    json_error('email is required -- only used to reissue your API key or delete your account later.', 400);
}

try {
    $result = register_account($pdo, $name, $email);
} catch (RuntimeException $e) {
    json_error($e->getMessage(), 409);
}

json_response($result);
