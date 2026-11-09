<?php
namespace Tests\Feature;
use App\Filament\Pages\{Customers,Staff,VpnUsers};
use App\Jobs\ApplyVpnCommand;
use App\Models\{AuditEvent,Customer,Node,ProvisioningCommand,User,VpnClient};
use App\Services\{AgentClient,NodeCollector,VpnCommands};
use Filament\Facades\Filament;
use Illuminate\Auth\Access\AuthorizationException;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\{Queue,Hash,Gate};
use Livewire\Livewire;
use Mockery;
use Tests\TestCase;

class AdminOperationsTest extends TestCase
{
    use RefreshDatabase;
    private function user(string $role='owner'): User { return User::create(['name'=>'Staff','email'=>$role.'@example.test','password'=>'Strong!Owner12345','role'=>$role,'active'=>true]); }
    protected function setUp(): void { parent::setUp(); Filament::setCurrentPanel(Filament::getPanel('admin')); }
    private function snapshot(int $up=100,string $epoch='boot1'): array { return ['clients'=>[['name'=>'phone','status'=>'active','expires_at'=>null,'ip_limit'=>1,'version'=>str_repeat('a',64)]],
        'services'=>['reality-vless'=>'active'],'observed_at'=>now()->toIso8601String(),'epoch'=>$epoch,'statistics_error'=>false,'online_ips'=>['phone'=>['198.51.100.1']],
        'traffic'=>['phone'=>['uplink'=>$up,'downlink'=>50]]]; }
    public function test_support_cannot_submit_privileged_vpn_changes(): void
    {
        $this->actingAs($this->user('support')); Queue::fake();
        $this->expectException(AuthorizationException::class);
        app(VpnCommands::class)->submit(Node::first(),['action'=>'add','name'=>'phone','days'=>30,'devices'=>1]);
    }
    public function test_disabled_staff_cannot_access_panel(): void
    {
        $user=$this->user(); $user->update(['active'=>false]);
        $this->assertFalse($user->canAccessPanel(Filament::getPanel('admin')));
        $this->actingAs($user)->get('/admin')->assertForbidden();
    }
    public function test_mfa_is_required_before_admin_dashboard_access(): void
    {
        $this->actingAs($this->user())->get('/admin')->assertRedirect();
        $this->assertTrue(Filament::getPanel('admin')->isMultiFactorAuthenticationRequired());
    }
    public function test_owner_can_create_customer_and_no_customer_login_is_created(): void
    {
        $owner=$this->user();
        Livewire::actingAs($owner)->test(Customers::class)->set('form.name','Customer One')->set('form.contact','09123456789')->call('saveRecord')->assertHasNoErrors();
        $this->assertDatabaseHas('customers',['name'=>'Customer One']); $this->assertDatabaseCount('users',1);
    }
    public function test_support_cannot_invoke_customer_write_even_if_it_calls_the_livewire_method_directly(): void
    {
        Livewire::actingAs($this->user('support'))->test(Customers::class)->set('form.name','Unauthorized')->call('saveRecord')->assertForbidden();
        $this->assertDatabaseCount('customers',0);
    }
    public function test_support_cannot_mount_the_staff_screen_directly(): void
    {
        Livewire::actingAs($this->user('support'))->test(Staff::class)->assertForbidden();
    }
    public function test_last_owner_cannot_disable_itself_and_password_never_enters_audit(): void
    {
        $owner=$this->user();
        Livewire::actingAs($owner)->test(Staff::class)->call('editRecord',$owner->id)->set('form.active',false)->call('saveRecord')->assertHasErrors();
        $this->assertTrue($owner->fresh()->active);
        $this->assertStringNotContainsString('Strong!Owner12345',AuditEvent::all()->toJson());
    }
    public function test_command_is_queued_with_stable_operation_and_expected_server_version(): void
    {
        Queue::fake(); $this->actingAs($this->user('operator'));
        $client=VpnClient::create(['node_id'=>Node::first()->id,'name'=>'phone','status'=>'active','ip_limit'=>1,'version'=>str_repeat('a',64)]);
        $command=app(VpnCommands::class)->submit(Node::first(),['action'=>'extend','name'=>'phone','days'=>30,'devices'=>1]);
        $this->assertSame('queued',$command->state); $this->assertSame($client->version,$command->payload['expected_version']);
        Queue::assertPushed(ApplyVpnCommand::class);
    }
    public function test_revoked_operator_does_not_execute_a_queued_command(): void
    {
        Queue::fake(); $user=$this->user('operator'); $this->actingAs($user);
        $command=app(VpnCommands::class)->submit(Node::first(),['action'=>'add','name'=>'phone','days'=>30,'devices'=>1]);
        $user->update(['active'=>false]);
        $agent=Mockery::mock(AgentClient::class); $agent->shouldNotReceive('request');
        (new ApplyVpnCommand($command->id))->handle($agent);
        $this->assertSame('failed',$command->fresh()->state);
    }
    public function test_an_already_authenticated_staff_session_loses_permission_after_demotion(): void
    {
        $owner=$this->user(); $this->actingAs($owner);
        $this->assertTrue(Gate::allows('owner'));
        User::whereKey($owner->id)->update(['role'=>'support']);
        $this->assertFalse(Gate::allows('owner'));
        $this->assertFalse(Gate::allows('manage-vpn'));
    }
    public function test_usage_polling_deduplicates_counters_and_accounts_for_restart(): void
    {
        $agent=Mockery::mock(AgentClient::class);
        $agent->shouldReceive('request')->andReturn($this->snapshot(100),$this->snapshot(100),$this->snapshot(20,'boot2'));
        $this->app->instance(AgentClient::class,$agent);
        $collector=app(NodeCollector::class);
        $collector->refresh(Node::first()); $collector->refresh(Node::first()); $collector->refresh(Node::first());
        $client=VpnClient::first(); $this->assertSame(120,$client->upload_bytes); $this->assertSame(100,$client->download_bytes);
    }
    public function test_delayed_lower_counter_sample_does_not_charge_the_same_bytes_twice(): void
    {
        $agent=Mockery::mock(AgentClient::class);
        $agent->shouldReceive('request')->andReturn($this->snapshot(100),$this->snapshot(60),$this->snapshot(120));
        $this->app->instance(AgentClient::class,$agent);
        for ($i=0;$i<3;$i++) app(NodeCollector::class)->refresh(Node::first());
        $this->assertSame(120,VpnClient::first()->upload_bytes);
        $this->assertSame(50,VpnClient::first()->download_bytes);
    }
    public function test_node_failure_keeps_cached_clients_and_marks_data_unavailable(): void
    {
        $agent=Mockery::mock(AgentClient::class); $agent->shouldReceive('request')->once()->andReturn($this->snapshot());
        $agent->shouldReceive('request')->once()->andThrow(new \RuntimeException('Unavailable'));
        $this->app->instance(AgentClient::class,$agent); app(NodeCollector::class)->refresh(Node::first());
        try { app(NodeCollector::class)->refresh(Node::first()); } catch (\RuntimeException) {}
        $this->assertDatabaseCount('vpn_clients',1); $this->assertNotNull(Node::first()->error);
    }
    public function test_mfa_secret_is_encrypted_and_hidden_from_serialization(): void
    {
        $user=$this->user(); $user->saveAppAuthenticationSecret('JBSWY3DPEHPK3PXP');
        $this->assertNotSame('JBSWY3DPEHPK3PXP',$user->getRawOriginal('app_authentication_secret'));
        $this->assertStringNotContainsString('JBSWY3DPEHPK3PXP',$user->toJson());
    }
}
