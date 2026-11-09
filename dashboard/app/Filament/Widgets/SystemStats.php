<?php
namespace App\Filament\Widgets;
use App\Models\{Node,ProvisioningCommand,VpnClient};
use Filament\Widgets\StatsOverviewWidget;
use Filament\Widgets\StatsOverviewWidget\Stat;

class SystemStats extends StatsOverviewWidget
{
    protected function getStats(): array
    {
        return [
            Stat::make('Active VPN accounts',VpnClient::where('status','active')->count())->description('Last collected server state'),
            Stat::make('Expiring within 7 days',VpnClient::where('status','active')->whereBetween('expires_at',[now(),now()->addDays(7)])->count()),
            Stat::make('Nodes needing attention',Node::where('enabled',true)->get()->filter(fn($node)=>$node->error || !$node->observed_at || $node->observed_at->lt(now()->subMinutes(3)) || !($node->health['healthy']??false))->count())->color('warning'),
            Stat::make('Failed operations',ProvisioningCommand::where('state','failed')->count())->color('danger'),
        ];
    }
}
