<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Set up Esmi VPN Admin</title>
<style>body{font:16px system-ui;background:#0c1424;color:#e9eef7;margin:0;display:grid;min-height:100vh;place-items:center}main{width:min(440px,86vw);padding:36px;background:#152137;border:1px solid #30405a;border-radius:18px}h1{font-size:27px}p{color:#aebdd2;line-height:1.6}label{display:block;margin-top:18px}input{box-sizing:border-box;width:100%;padding:12px;margin-top:7px;border-radius:8px;border:1px solid #4b5b74;background:#0c1424;color:white;font:inherit}button{width:100%;margin-top:25px;padding:13px;background:#44d7b6;border:0;border-radius:8px;font:700 16px system-ui;color:#072a25}.error{color:#ffb4b4}</style></head>
<body><main><p>ESMI VPN · FIRST ADMINISTRATOR</p><h1>Secure your dashboard</h1><p>Enter the eight-character key shown in the server terminal. This setup closes after the first administrator is created.</p>
@if($errors->any())<p class="error" role="alert">{{ $errors->first() }}</p>@endif
<form method="post" action="{{ route('setup') }}">@csrf
<label>Setup key<input name="setup_key" type="password" minlength="8" maxlength="8" autocomplete="off" required></label>
<label>Your name<input name="name" maxlength="100" autocomplete="name" required></label>
<label>Admin email<input name="email" type="email" maxlength="254" autocomplete="username" required></label>
<label>Password<input name="password" type="password" minlength="14" maxlength="128" autocomplete="new-password" required></label>
<p>Use at least 14 characters with uppercase, lowercase, a number and a symbol.</p>
<label>Confirm password<input name="password_confirmation" type="password" minlength="14" maxlength="128" autocomplete="new-password" required></label>
<button>Create administrator</button></form><p>Authenticator enrollment is required after sign-in.</p></main></body></html>
