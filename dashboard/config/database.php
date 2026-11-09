<?php
return [
    'default' => 'sqlite',
    'connections' => ['sqlite' => ['driver' => 'sqlite', 'database' => env('DB_DATABASE', database_path('database.sqlite')),
        'prefix' => '', 'foreign_key_constraints' => true, 'busy_timeout' => 10000, 'journal_mode' => 'WAL', 'synchronous' => 'FULL']],
    'migrations' => ['table' => 'migrations', 'update_date_on_publish' => true],
];
