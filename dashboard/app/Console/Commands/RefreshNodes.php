<?php
namespace App\Console\Commands;
use App\Models\Node;
use App\Services\NodeCollector;
use Illuminate\Console\Command;
class RefreshNodes extends Command
{
    protected $signature='admin:refresh';
    protected $description='Refresh VPN status and aggregate counters from enabled private agents';
    public function handle(NodeCollector $collector): int
    {
        $failed=false;
        foreach (Node::where('enabled',true)->cursor() as $node) {
            try { $collector->refresh($node); } catch (\Throwable) { $this->warn('Node '.$node->id.' needs attention.'); $failed=true; }
        }
        return $failed?self::FAILURE:self::SUCCESS;
    }
}
