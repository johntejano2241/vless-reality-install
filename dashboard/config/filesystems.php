<?php
return ['default' => 'local', 'disks' => [
    'local' => ['driver' => 'local', 'root' => storage_path('app/private'), 'throw' => false],
    'public' => ['driver' => 'local', 'root' => storage_path('app/public'), 'url' => env('APP_URL').'/storage', 'visibility' => 'public', 'throw' => false],
], 'links' => []];
