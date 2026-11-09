<?php
namespace App\Jobs;
use App\Models\{AuditEvent,ProvisioningCommand,User};
use App\Services\{AgentClient,NodeCollector,StaleOperation};
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;

class ApplyVpnCommand implements ShouldQueue
{
    use Queueable;
    public int $tries=3;
    public int $timeout=110;
    public function __construct(public int $commandId) {}
    public function backoff(): array { return [5,20]; }
    public function handle(AgentClient $agent): void
    {
        $command=ProvisioningCommand::findOrFail($this->commandId);
        if (in_array($command->state,['succeeded','failed'],true)) return;
        $actor=User::find($command->actor_id);
        if (!$actor?->active || !in_array($actor->role,['owner','operator'],true)) {
            $command->update(['state'=>'failed','error'=>'Submitting staff member is no longer authorized.']); return;
        }
        $command->update(['state'=>'running','error'=>null]);
        try {
            $agent->request($command->node,'POST','/v1/commands',$command->payload);
            $command->update(['state'=>'succeeded']);
            AuditEvent::write('vpn.command.applied',$command->client_name,['command_id'=>$command->id,'node_id'=>$command->node_id],$actor->id);
        } catch (StaleOperation $error) {
            $command->update(['state'=>'failed','error'=>'Client changed. Refresh and submit the operation again.']); return;
        }
        // Refresh is separate from the mutation: failure cannot repeat a successful grant.
        try { app(NodeCollector::class)->refresh($command->node); } catch (\Throwable) {}
    }
    public function failed(?\Throwable $error): void
    {
        ProvisioningCommand::whereKey($this->commandId)->where('state','!=','succeeded')
            ->update(['state'=>'failed','error'=>'VPN manager unavailable. Inspect the node, then submit a fresh operation.']);
    }
}
