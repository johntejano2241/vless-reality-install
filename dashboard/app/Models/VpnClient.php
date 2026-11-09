<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class VpnClient extends Model
{
    protected $fillable = ['node_id','name','status','expires_at','ip_limit','version','customer_id','plan_id','online_ips','upload_bytes','download_bytes','counter_epoch','last_upload','last_download'];
    protected function casts(): array { return ['expires_at'=>'datetime','online_ips'=>'array','upload_bytes'=>'integer','download_bytes'=>'integer']; }
    public function node() { return $this->belongsTo(Node::class); }
}

