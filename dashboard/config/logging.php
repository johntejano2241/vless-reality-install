<?php
return ['default' => 'stderr', 'channels' => [
    'stderr' => ['driver' => 'monolog', 'level' => 'warning', 'handler' => Monolog\Handler\StreamHandler::class,
        'with' => ['stream' => 'php://stderr'], 'replace_placeholders' => true],
    'null' => ['driver' => 'monolog', 'handler' => Monolog\Handler\NullHandler::class],
]];
