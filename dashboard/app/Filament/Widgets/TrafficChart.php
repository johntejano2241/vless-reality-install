<?php
namespace App\Filament\Widgets;
use App\Models\VpnClient;
use Filament\Widgets\ChartWidget;
class TrafficChart extends ChartWidget
{
    public function getHeading(): ?string { return 'Collected account traffic (GiB)'; }
    protected function getType(): string { return 'bar'; }
    protected function getData(): array
    {
        $clients=VpnClient::orderByRaw('(upload_bytes + download_bytes) DESC')->limit(10)->get();
        return ['labels'=>$clients->map(fn($client)=>$client->node_id.': '.$client->name)->all(),'datasets'=>[
            ['label'=>'Upload','data'=>$clients->map(fn($client)=>round($client->upload_bytes/1073741824,3))->all(),'backgroundColor'=>'#14b8a6'],
            ['label'=>'Download','data'=>$clients->map(fn($client)=>round($client->download_bytes/1073741824,3))->all(),'backgroundColor'=>'#3b82f6'],
        ]];
    }
}
