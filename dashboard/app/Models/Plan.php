<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class Plan extends Model
{
    protected $fillable = ['name','days','ip_limit','region','active'];
    protected function casts(): array { return ['days'=>'integer','ip_limit'=>'integer','active'=>'boolean']; }
    
}

