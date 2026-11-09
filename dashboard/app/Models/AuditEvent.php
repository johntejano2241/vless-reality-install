<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class AuditEvent extends Model
{
    public $timestamps = false;
    protected $guarded = [];
    protected function casts(): array { return ['details'=>'array','created_at'=>'datetime']; }
    public static function write(string $action, string $target, array $details = [], ?int $actor = null): void
    {
        static::create(['actor_id'=>$actor ?? auth()->id(), 'action'=>$action,'target'=>$target,
            'details'=>array_intersect_key($details,array_flip(['role','active','state','node_id','command_id']))]);
    }
}
