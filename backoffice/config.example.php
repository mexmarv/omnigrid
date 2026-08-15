<?php
/**
 * Copy this file to config.php and fill in your own database details.
 * config.php is gitignored -- never commit real credentials.
 */

// MySQL (recommended on Hostinger shared hosting -- create a database
// and user in hPanel's "Databases" section first, then fill these in):
return [
    'dsn' => 'mysql:host=localhost;dbname=YOUR_DB_NAME;charset=utf8mb4',
    'db_user' => 'YOUR_DB_USER',
    'db_pass' => 'YOUR_DB_PASSWORD',
];

// SQLite instead (simpler, no separate database needed -- but confirm
// your hosting plan allows the PHP process to write files):
//
// return [
//     'dsn' => 'sqlite:' . __DIR__ . '/data/omnigrid.sqlite',
//     'db_user' => null,
//     'db_pass' => null,
// ];
