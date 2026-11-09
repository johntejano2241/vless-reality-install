<?php
namespace App\Console\Commands;
use App\Models\{AuditEvent,User};
use Illuminate\Console\Command;
use Illuminate\Support\Facades\{DB,Validator};
use Illuminate\Validation\Rules\Password;
class RecoverAdmin extends Command
{
    protected $signature='admin:recover {email}';
    protected $description='Server-console recovery: replace an owner password and reset lost MFA';
    public function handle(): int
    {
        if (function_exists('posix_geteuid') && posix_geteuid()!==0) { $this->error('Run from the root server console / docker compose exec --user 0.'); return self::FAILURE; }
        $email=strtolower($this->argument('email'));
        $password=$this->secret('New owner password (minimum 14, mixed case, number and symbol)');
        $confirmation=$this->secret('Confirm new password');
        Validator::make(['email'=>$email,'password'=>$password,'password_confirmation'=>$confirmation],
            ['email'=>'required|email','password'=>['required','confirmed',Password::min(14)->mixedCase()->numbers()->symbols(),'max:128']])->validate();
        DB::transaction(function () use ($email,$password) {
            $user=User::firstOrNew(['email'=>$email]);
            $user->fill(['name'=>$user->name?:'Recovered administrator','password'=>$password,'role'=>'owner','active'=>true]);
            $user->app_authentication_secret=null; $user->app_authentication_recovery_codes=null; $user->remember_token=null; $user->save();
            DB::table('sessions')->where('user_id',$user->id)->delete();
            DB::table('setup_states')->where('id',1)->update(['completed_at'=>now(),'key_hash'=>null,'expires_at'=>null]);
            AuditEvent::write('admin.console_recovery',(string)$user->id,[],$user->id);
        });
        $this->info('Owner recovered. Sign in and enroll MFA again. First-time setup remains closed.');
        return self::SUCCESS;
    }
}
