<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class SetupState extends Model
{
    public $timestamps = false;
    protected $guarded = [];
    protected $hidden = ['key_hash'];
    protected function casts(): array { return ['expires_at'=>'datetime','completed_at'=>'datetime']; }
}
