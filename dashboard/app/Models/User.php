<?php
namespace App\Models;

use Filament\Auth\MultiFactor\App\Concerns\InteractsWithAppAuthentication;
use Filament\Auth\MultiFactor\App\Concerns\InteractsWithAppAuthenticationRecovery;
use Filament\Auth\MultiFactor\App\Contracts\HasAppAuthentication;
use Filament\Auth\MultiFactor\App\Contracts\HasAppAuthenticationRecovery;
use Filament\Models\Contracts\FilamentUser;
use Filament\Panel;
use Illuminate\Foundation\Auth\User as Authenticatable;

class User extends Authenticatable implements FilamentUser, HasAppAuthentication, HasAppAuthenticationRecovery
{
    use InteractsWithAppAuthentication, InteractsWithAppAuthenticationRecovery;
    use \Illuminate\Notifications\Notifiable;
    protected $fillable = ['name','email','password','role','active'];
    protected $hidden = ['password','remember_token'];
    protected function casts(): array { return ['password'=>'hashed','active'=>'boolean']; }
    public function canAccessPanel(Panel $panel): bool { return $this->active && in_array($this->role, ['owner','operator','support'], true); }
}
