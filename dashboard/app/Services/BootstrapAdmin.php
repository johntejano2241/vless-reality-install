<?php
namespace App\Services;
use App\Models\{AuditEvent,SetupState,User};
use Illuminate\Support\Facades\{DB,Hash};
use Illuminate\Support\Str;
use Illuminate\Validation\ValidationException;

class BootstrapAdmin
{
    public function available(): bool
    {
        $state = SetupState::find(1);
        return $state && !$state->completed_at && !User::exists() && $state->key_hash && $state->expires_at?->isFuture() && $state->attempts < 10;
    }

    public function issue(): ?string
    {
        return DB::transaction(function () {
            $state = SetupState::lockForUpdate()->findOrFail(1);
            if (User::exists() || $state->completed_at) return null;
            $key = Str::random(8);
            $state->update(['key_hash'=>Hash::make($key),'expires_at'=>now()->addMinutes(config('admin.setup_minutes')),'attempts'=>0]);
            return $key;
        }, 3);
    }

    public function claim(array $data): User
    {
        // Return the failure from the transaction so failed-attempt updates commit.
        $user = DB::transaction(function () use ($data) {
            $state = SetupState::lockForUpdate()->findOrFail(1);
            if ($state->completed_at || User::exists() || !$state->key_hash || !$state->expires_at?->isFuture() || $state->attempts >= 10) return null;
            if (!Hash::check($data['setup_key'], $state->key_hash)) {
                $state->increment('attempts');
                if ($state->attempts >= 10) $state->update(['key_hash'=>null,'expires_at'=>null]);
                return null;
            }
            // CAS also protects engines where SELECT FOR UPDATE has no row-lock semantics.
            $claimed = SetupState::whereKey(1)->whereNull('completed_at')->where('key_hash',$state->key_hash)
                ->update(['key_hash'=>null,'expires_at'=>null,'completed_at'=>now()]);
            if ($claimed !== 1) return null;
            $user = User::create(['name'=>$data['name'],'email'=>strtolower($data['email']),
                'password'=>$data['password'],'role'=>'owner','active'=>true]);
            AuditEvent::write('admin.bootstrap', (string)$user->id, [], $user->id);
            return $user;
        }, 3);
        if (!$user) throw ValidationException::withMessages(['setup_key'=>'Setup unavailable or key invalid. Ask the server operator to check setup.']);
        return $user;
    }
}
