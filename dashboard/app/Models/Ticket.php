<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class Ticket extends Model
{
    protected $fillable = ['customer_id','subject','notes','status'];
    protected function casts(): array { return []; }
    
}

