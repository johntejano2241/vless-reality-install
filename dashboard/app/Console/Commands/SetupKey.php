<?php
namespace App\Console\Commands;
use App\Services\BootstrapAdmin;
use Illuminate\Console\Command;

class SetupKey extends Command
{
    protected $signature = 'admin:setup-key';
    protected $description = 'Issue an eight-character first-admin setup key when setup is still unclaimed';
    public function handle(BootstrapAdmin $bootstrap): int
    {
        $key = $bootstrap->issue();
        if ($key === null) { $this->info('Admin setup is closed. Existing administrator credentials were preserved.'); return self::SUCCESS; }
        $this->line('Setup URL: '.rtrim(config('app.url'),'/').'/setup');
        $this->line('Setup key: '.$key);
        $this->line('Valid for 30 minutes, one use. Keep this terminal output private.');
        return self::SUCCESS;
    }
}
