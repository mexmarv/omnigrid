<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();

$id = (int)($_GET['id'] ?? 0);
$stmt = $pdo->prepare('SELECT * FROM jobs WHERE id = ?');
$stmt->execute([$id]);
$job = $stmt->fetch();
if ($job === false) {
    json_error('Unknown job.', 404);
}
json_response($job);
