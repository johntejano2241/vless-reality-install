<?php
namespace App\Console\Commands;
use App\Jobs\ApplyVpnCommand;
use App\Models\ProvisioningCommand;
use Illuminate\Console\Command;

class DispatchPending extends Command
{
    protected $signature='admin:dispatch-pending';
    protected $description='Recover a committed VPN command if a worker or enqueue operation was interrupted';
    public function handle(): int
    {
        foreach (ProvisioningCommand::whereIn('state',['queued','running'])->where('updated_at','<',now()->subMinutes(5))->limit(50)->get() as $command) {
            if (ProvisioningCommand::whereKey($command->id)->where('updated_at',$command->updated_at)->update(['updated_at'=>now()])) ApplyVpnCommand::dispatch($command->id);
        }
        return self::SUCCESS;
    }
}
