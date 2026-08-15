<?php
/**
 * Database connection + schema bootstrap. Supports MySQL (recommended for
 * Hostinger shared hosting) or SQLite, picked by the DSN in config.php.
 */

function omnigrid_db(): PDO {
    static $pdo = null;
    if ($pdo !== null) {
        return $pdo;
    }

    $configPath = __DIR__ . '/config.php';
    if (!file_exists($configPath)) {
        http_response_code(500);
        header('Content-Type: application/json');
        echo json_encode(['detail' => 'config.php is missing -- copy config.example.php to config.php and fill in your database details.']);
        exit;
    }
    $config = require $configPath;

    $pdo = new PDO($config['dsn'], $config['db_user'] ?? null, $config['db_pass'] ?? null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);

    $isSqlite = str_starts_with($config['dsn'], 'sqlite:');
    $idType = $isSqlite ? 'INTEGER PRIMARY KEY AUTOINCREMENT' : 'INT AUTO_INCREMENT PRIMARY KEY';
    $realType = $isSqlite ? 'REAL' : 'DOUBLE';
    $textType = $isSqlite ? 'TEXT' : 'LONGTEXT';

    $pdo->exec("CREATE TABLE IF NOT EXISTS accounts (
        id $idType,
        name VARCHAR(255) NOT NULL UNIQUE,
        api_key_hash CHAR(64) NOT NULL UNIQUE,
        credits $realType NOT NULL DEFAULT 50.0,
        created_at $realType NOT NULL
    )");

    $pdo->exec("CREATE TABLE IF NOT EXISTS providers (
        id $idType,
        account_id INT NOT NULL,
        cpu_cores $realType NOT NULL,
        ram_mb INT NOT NULL,
        gpu_model VARCHAR(255),
        gpu_vram_mb INT,
        task_types TEXT NOT NULL,
        last_heartbeat $realType NOT NULL,
        busy INT NOT NULL DEFAULT 0
    )");

    $pdo->exec("CREATE TABLE IF NOT EXISTS jobs (
        id $idType,
        consumer_account_id INT NOT NULL,
        provider_id INT,
        task_type VARCHAR(255) NOT NULL,
        payload_format VARCHAR(20) NOT NULL,
        payload_b64 $textType NOT NULL,
        cpu_limit $realType NOT NULL,
        ram_limit_mb INT NOT NULL,
        gpu_required INT NOT NULL DEFAULT 0,
        timeout_s INT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'queued',
        error TEXT,
        result_format VARCHAR(20),
        result_b64 $textType,
        compute_seconds $realType,
        created_at $realType NOT NULL,
        finished_at $realType
    )");

    return $pdo;
}
