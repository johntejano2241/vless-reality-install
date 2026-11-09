<?php
namespace App\Services;
use App\Models\{Node,User,VpnClient};
use Filament\Notifications\Notification;
use Illuminate\Support\Facades\{DB,Validator};

class NodeCollector
{
    public function refresh(Node $node): void
    {
        try {
            $data = app(AgentClient::class)->request($node,'GET','/v1/snapshot');
            Validator::make($data,[
                'clients'=>'required|array','services'=>'required|array','observed_at'=>'required|date',
                'epoch'=>'present|string','statistics_error'=>'required|boolean',
                'clients.*.name'=>['required','regex:/^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/D'],
                'clients.*.status'=>'required|in:active,expired,suspended','clients.*.expires_at'=>'nullable|date',
                'clients.*.ip_limit'=>'required|integer|min:0','clients.*.version'=>'required|string|size:64',
            ])->validate();
            DB::transaction(function () use ($node,$data) {
                $names=[];
                foreach ($data['clients'] as $record) {
                    $names[]=$record['name'];
                    $client=VpnClient::firstOrNew(['node_id'=>$node->id,'name'=>$record['name']]);
                    $client->fill(['status'=>$record['status'],'expires_at'=>$record['expires_at'],'ip_limit'=>$record['ip_limit'],'version'=>$record['version'],
                        'online_ips'=>$data['statistics_error'] ? null : ($data['online_ips'][strtolower($record['name'])] ?? [])]);
                    if (!$data['statistics_error'] && $data['epoch'] && isset($data['traffic'])) {
                        $counts=$data['traffic'][$record['name']] ?? [];
                        $up=max(0,(int)($counts['uplink']??0)); $down=max(0,(int)($counts['downlink']??0));
                        $same=$client->counter_epoch === $data['epoch'];
                        $client->upload_bytes=($client->upload_bytes??0)+max(0,$up-($same?$client->last_upload:0));
                        $client->download_bytes=($client->download_bytes??0)+max(0,$down-($same?$client->last_download:0));
                        $client->last_upload=$up; $client->last_download=$down; $client->counter_epoch=$data['epoch'];
                    }
                    $client->save();
                }
                VpnClient::where('node_id',$node->id)->whereNotIn('name',$names)->delete();
                $resources=$data['resources']??null;
                $lowDisk=$resources && ($resources['disk_total']??0)>0 && $resources['disk_used']/$resources['disk_total']>=.9;
                $healthy=!$data['statistics_error'] && !array_filter($data['services'],fn($state)=>$state!=='active') && !$lowDisk;
                $wasHealthy=$node->health['healthy']??true;
                $node->update(['health'=>['services'=>$data['services'],'statistics_error'=>$data['statistics_error'],'healthy'=>$healthy,'resources'=>$resources],
                    'observed_at'=>now(),'error'=>null]);
                if ($wasHealthy && !$healthy) Notification::make()->title('VPN server needs attention')->body($node->name.' has an unhealthy service or unavailable statistics.')->danger()->sendToDatabase(User::where('active',true)->where('role','owner')->get());
            });
        } catch (\Throwable $error) {
            // Never retain raw response bodies, profiles, credentials or request payloads.
            $alreadyFailed=(bool)$node->error;
            $node->update(['error'=>'Node refresh failed. Inspect the private agent and connectivity.']);
            if (!$alreadyFailed) Notification::make()->title('VPN server unreachable')->body($node->name.' could not be refreshed.')->danger()->sendToDatabase(User::where('active',true)->where('role','owner')->get());
            throw new \RuntimeException('Node refresh failed.', previous: $error);
        }
    }
}
