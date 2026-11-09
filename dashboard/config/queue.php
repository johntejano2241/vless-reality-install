<?php
return ['default' => env('QUEUE_CONNECTION', 'database'), 'connections' => [
    'sync' => ['driver' => 'sync'],
    'database' => ['driver' => 'database', 'connection' => null, 'table' => 'jobs', 'queue' => 'default', 'retry_after' => 150, 'after_commit' => true],
], 'failed' => ['driver' => 'database-uuids', 'database' => 'sqlite', 'table' => 'failed_jobs']];
