<?php
namespace App\Providers;
use App\Filament\Pages;
use App\Filament\Widgets\{SystemStats,TrafficChart};
use Filament\Auth\MultiFactor\App\AppAuthentication;
use Filament\Http\Middleware\{Authenticate,DisableBladeIconComponents,DispatchServingFilamentEvent};
use Filament\Panel;
use Filament\PanelProvider;
use Filament\Support\Colors\Color;
use Illuminate\Cookie\Middleware\{AddQueuedCookiesToResponse,EncryptCookies};
use Illuminate\Foundation\Http\Middleware\VerifyCsrfToken;
use Illuminate\Routing\Middleware\SubstituteBindings;
use Illuminate\Session\Middleware\{AuthenticateSession,StartSession};
use Illuminate\View\Middleware\ShareErrorsFromSession;

class AdminPanelProvider extends PanelProvider
{
    public function panel(Panel $panel): Panel
    {
        return $panel->default()->id('admin')->path('admin')->brandName('Esmi VPN Admin')
            ->login()->profile()->databaseNotifications()->colors(['primary'=>Color::Teal])
            ->multiFactorAuthentication([AppAuthentication::make()->recoverable()->codeWindow(1)],isRequired:true)
            ->pages([\Filament\Pages\Dashboard::class,Pages\VpnUsers::class,Pages\Customers::class,
                Pages\Plans::class,Pages\Nodes::class,Pages\Staff::class,Pages\Tickets::class,Pages\Operations::class,Pages\AuditLog::class])
            ->widgets([SystemStats::class,TrafficChart::class])
            ->middleware([EncryptCookies::class,AddQueuedCookiesToResponse::class,StartSession::class,AuthenticateSession::class,
                ShareErrorsFromSession::class,VerifyCsrfToken::class,SubstituteBindings::class,DisableBladeIconComponents::class,DispatchServingFilamentEvent::class])
            ->authMiddleware([Authenticate::class],isPersistent:true);
    }
}
