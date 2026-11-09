<?php
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('users', function (Blueprint $t) {
            $t->id(); $t->string('name'); $t->string('email')->unique(); $t->string('password');
            $t->string('role')->default('support'); $t->boolean('active')->default(true); $t->rememberToken();
            $t->text('app_authentication_secret')->nullable(); $t->text('app_authentication_recovery_codes')->nullable(); $t->timestamps();
        });
        Schema::create('setup_states', function (Blueprint $t) {
            $t->unsignedInteger('id')->primary(); $t->string('key_hash')->nullable(); $t->timestamp('expires_at')->nullable();
            $t->timestamp('completed_at')->nullable(); $t->unsignedInteger('attempts')->default(0);
        });
        DB::table('setup_states')->insert(['id' => 1]);
        Schema::create('sessions', function (Blueprint $t) {
            $t->string('id')->primary(); $t->foreignId('user_id')->nullable()->index(); $t->string('ip_address',45)->nullable();
            $t->text('user_agent')->nullable(); $t->longText('payload'); $t->integer('last_activity')->index();
        });
        Schema::create('cache', function (Blueprint $t) { $t->string('key')->primary(); $t->mediumText('value'); $t->integer('expiration'); });
        Schema::create('cache_locks', function (Blueprint $t) { $t->string('key')->primary(); $t->string('owner'); $t->integer('expiration'); });
        Schema::create('jobs', function (Blueprint $t) {
            $t->id(); $t->string('queue')->index(); $t->longText('payload'); $t->unsignedTinyInteger('attempts');
            $t->unsignedInteger('reserved_at')->nullable(); $t->unsignedInteger('available_at'); $t->unsignedInteger('created_at');
        });
        Schema::create('failed_jobs', function (Blueprint $t) {
            $t->id(); $t->string('uuid')->unique(); $t->text('connection'); $t->text('queue');
            $t->longText('payload'); $t->longText('exception'); $t->timestamp('failed_at')->useCurrent();
        });
        Schema::create('customers', function (Blueprint $t) {
            $t->id(); $t->string('name'); $t->string('contact')->nullable(); $t->text('notes')->nullable(); $t->timestamps();
        });
        Schema::create('plans', function (Blueprint $t) {
            $t->id(); $t->string('name'); $t->unsignedInteger('days'); $t->unsignedInteger('ip_limit')->default(0);
            $t->string('region')->default('Singapore'); $t->boolean('active')->default(true); $t->timestamps();
        });
        Schema::create('nodes', function (Blueprint $t) {
            $t->id(); $t->string('name'); $t->string('region'); $t->string('socket_name')->unique();
            $t->boolean('enabled')->default(true); $t->json('health')->nullable(); $t->timestamp('observed_at')->nullable();
            $t->string('error')->nullable(); $t->timestamps();
        });
        DB::table('nodes')->insert(['name'=>'Local server','region'=>'Singapore','socket_name'=>'agent','enabled'=>true,'created_at'=>now(),'updated_at'=>now()]);
        Schema::create('vpn_clients', function (Blueprint $t) {
            $t->id(); $t->foreignId('node_id')->constrained(); $t->string('name'); $t->string('status');
            $t->timestamp('expires_at')->nullable(); $t->unsignedInteger('ip_limit')->default(0); $t->string('version');
            $t->foreignId('customer_id')->nullable()->constrained(); $t->foreignId('plan_id')->nullable()->constrained();
            $t->json('online_ips')->nullable(); $t->unsignedBigInteger('upload_bytes')->default(0); $t->unsignedBigInteger('download_bytes')->default(0);
            $t->string('counter_epoch')->nullable(); $t->unsignedBigInteger('last_upload')->default(0); $t->unsignedBigInteger('last_download')->default(0);
            $t->timestamps(); $t->unique(['node_id','name']);
        });
        Schema::create('provisioning_commands', function (Blueprint $t) {
            $t->id(); $t->uuid('operation_id')->unique(); $t->foreignId('node_id')->constrained(); $t->foreignId('actor_id')->constrained('users');
            $t->string('action'); $t->string('client_name'); $t->json('payload'); $t->string('state')->default('queued');
            $t->string('error')->nullable(); $t->timestamps();
        });
        Schema::create('tickets', function (Blueprint $t) {
            $t->id(); $t->foreignId('customer_id')->nullable()->constrained(); $t->string('subject'); $t->text('notes');
            $t->string('status')->default('open'); $t->timestamps();
        });
        Schema::create('audit_events', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('actor_id')->nullable(); $t->string('action'); $t->string('target');
            $t->json('details')->nullable(); $t->timestamp('created_at')->useCurrent();
        });
    }
    public function down(): void
    {
        foreach (['audit_events','tickets','provisioning_commands','vpn_clients','nodes','plans','customers','failed_jobs','jobs','cache_locks','cache','sessions','setup_states','users'] as $table) Schema::dropIfExists($table);
    }
};
