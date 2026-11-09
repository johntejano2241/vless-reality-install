<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class Node extends Model
{
    protected $fillable = ['name','region','socket_name','enabled','health','observed_at','error'];
    protected function casts(): array { return ['enabled'=>'boolean','health'=>'array','observed_at'=>'datetime']; }
    
}

