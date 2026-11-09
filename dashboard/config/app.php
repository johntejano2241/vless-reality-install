<?php
return [
    'name' => 'Esmi VPN Admin', 'env' => env('APP_ENV', 'production'), 'debug' => (bool) env('APP_DEBUG', false),
    'url' => env('APP_URL', 'http://localhost:8080'), 'timezone' => 'UTC', 'locale' => 'en', 'fallback_locale' => 'en',
    'faker_locale' => 'en_US', 'cipher' => 'AES-256-CBC', 'key' => env('APP_KEY'),
    'previous_keys' => [], 'maintenance' => ['driver' => 'file'],
    'aliases' => Illuminate\Support\Facades\Facade::defaultAliases()->toArray(),
];
