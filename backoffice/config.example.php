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

    // Sending address for reset.php's account-recovery emails. Defaults to
    // no-reply@<your domain> if you leave this out entirely. Using an
    // address on your own domain (e.g. one you already have a mailbox for
    // in hPanel) generally delivers more reliably than a made-up no-reply@
    // address, since your domain's mail server already has its own
    // SPF/DKIM set up.
    'mail_from' => 'no-reply@chanza.ai',

    // Optional: share a free build.nvidia.com vision-language model directly from
    // this server -- no separate always-on client process needed, since relaying
    // to NVIDIA's API is just an outbound HTTP call this already-running PHP
    // process can make itself. Uncomment and fill in your own key:
    //
    // 'nvidia_models' => [
    //     'my-vision-model' => [
    //         'api_key' => 'nvapi-your-own-key',
    //         'model_id' => 'meta/llama-3.2-90b-vision-instruct',
    //     ],
    // ],
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
//     'mail_from' => 'no-reply@chanza.ai',
// ];
