<?php
/**
 * Copy this file to config.php. config.php is gitignored -- never commit
 * real credentials.
 */

// SQLite (recommended): one file, no separate database service to manage,
// no credentials to leak. Just make sure data/ is writable by PHP.
return [
    'dsn' => 'sqlite:' . __DIR__ . '/data/omnigrid.sqlite',
    'db_user' => null,
    'db_pass' => null,
];

// MySQL instead, if you'd rather use a managed database (e.g. you already
// have one, or expect heavy concurrent write load SQLite's single-writer
// model wouldn't love) -- create a database and user in hPanel's
// "Databases" section first, then fill these in:
//
// return [
//     'dsn' => 'mysql:host=localhost;dbname=YOUR_DB_NAME;charset=utf8mb4',
//     'db_user' => 'YOUR_DB_USER',
//     'db_pass' => 'YOUR_DB_PASSWORD',
// ];
