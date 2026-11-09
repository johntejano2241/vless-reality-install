<?php
namespace App\Services;
use App\Jobs\ApplyVpnCommand;
use App\Models\{AuditEvent,Node,ProvisioningCommand,VpnClient};
use Illuminate\Support\Facades\{DB,Gate,Validator};
use Illuminate\Support\Str;

class VpnCommands
{
    public function submit(Node $node, array $input): ProvisioningCommand
    {
        Gate::authorize('manage-vpn');
        $data=Validator::make($input,[
            'action'=>'required|in:add,extend,suspend,resume,rotate,set-limit,remove',
            'name'=>['required','regex:/^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/D'],
            'days'=>'required|integer|min:0|max:36500','devices'=>'required|integer|min:0|max:1000',
        ])->validate();
        abort_unless($node->enabled,422);
        $client=VpnClient::where('node_id',$node->id)->where('name',$data['name'])->first();
        if ($data['action']!=='add') abort_unless($client,422);
        return DB::transaction(function () use ($node,$data,$client) {
            $id=(string)Str::uuid();
            $payload=['operation_id'=>$id,'action'=>$data['action'],'name'=>$data['name'],
                'days'=>(int)$data['days'],'devices'=>(int)$data['devices'],'expected_version'=>$client?->version];
            $command=ProvisioningCommand::create(['operation_id'=>$id,'node_id'=>$node->id,'actor_id'=>auth()->id(),
                'action'=>$data['action'],'client_name'=>$data['name'],'payload'=>$payload,'state'=>'queued']);
            AuditEvent::write('vpn.command.queued',$data['name'],['command_id'=>$command->id,'node_id'=>$node->id]);
            ApplyVpnCommand::dispatch($command->id)->afterCommit();
            return $command;
        });
    }
}
