<?php
require_once __DIR__ . '/../lib.php';
$pdo = omnigrid_db();

json_response(dashboard_snapshot($pdo));
