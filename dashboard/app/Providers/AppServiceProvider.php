<?php
namespace App\Providers;
use App\Models\{AuditEvent,User};
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Support\Facades\{Event,Gate,RateLimiter};
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    public function boot(): void
    {
        \Illuminate\Validation\Rules\Password::defaults(fn()=>\Illuminate\Validation\Rules\Password::min(14)->mixedCase()->numbers()->symbols());
        Gate::define('owner',fn(User $user)=>$user->active && $user->role==='owner');
        if (str_starts_with(config('app.url'),'https://')) \Illuminate\Support\Facades\URL::forceScheme('https');
        Gate::define('manage-vpn',fn(User $user)=>$user->active && in_array($user->role,['owner','operator'],true));
        Gate::define('staff',fn(User $user)=>$user->active && in_array($user->role,['owner','operator','support'],true));
        RateLimiter::for('setup',fn($request)=>Limit::perMinutes(15,5)->by('setup:'.$request->ip()));
        Event::listen(\Illuminate\Auth\Events\Login::class,fn($event)=>AuditEvent::write('admin.login',(string)$event->user->id,[],$event->user->id));
    }
}
