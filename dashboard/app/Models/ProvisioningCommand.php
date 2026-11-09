<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class ProvisioningCommand extends Model
{
    protected $fillable = ['operation_id','node_id','actor_id','action','client_name','payload','state','error'];
    protected function casts(): array { return ['payload'=>'array']; }
    public function node() { return $this->belongsTo(Node::class); }
}

