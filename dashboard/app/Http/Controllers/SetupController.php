<?php
namespace App\Http\Controllers;
use App\Services\BootstrapAdmin;
use Illuminate\Http\Request;
use Illuminate\Validation\Rules\Password;

class SetupController
{
    public function show(BootstrapAdmin $bootstrap)
    {
        abort_unless($bootstrap->available(), 404);
        return view('setup');
    }
    public function store(Request $request, BootstrapAdmin $bootstrap)
    {
        abort_unless($bootstrap->available(), 404);
        $data = $request->validate(['setup_key'=>['required','string','size:8','regex:/^[A-Za-z0-9]{8}$/'],
            'name'=>['required','string','max:100'],'email'=>['required','email','max:254'],
            'password'=>['required','confirmed',Password::min(14)->mixedCase()->numbers()->symbols(),'max:128']]);
        $bootstrap->claim($data);
        $request->session()->invalidate();
        $request->session()->regenerateToken();
        return redirect('/admin/login')->with('status','Administrator created. Sign in and enroll your authenticator.');
    }
}
