<?php
namespace Tests\Feature;
use App\Models\{SetupState,User};
use App\Services\BootstrapAdmin;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Hash;
use Illuminate\Validation\ValidationException;
use Tests\TestCase;

class BootstrapAdminTest extends TestCase
{
    use RefreshDatabase;
    private function data(string $key): array { return ['setup_key'=>$key,'name'=>'Owner','email'=>'owner@example.test','password'=>'Strong!Owner12345']; }
    public function test_key_is_exactly_eight_alphanumeric_characters_and_only_its_hash_is_stored(): void
    {
        $key=app(BootstrapAdmin::class)->issue();
        $this->assertMatchesRegularExpression('/^[A-Za-z0-9]{8}$/D',$key);
        $state=SetupState::find(1);
        $this->assertNotSame($key,$state->key_hash);
        $this->assertTrue(Hash::check($key,$state->key_hash));
        $this->assertTrue($state->expires_at->equalTo(now()->addMinutes(30)->startOfSecond()));
        $this->assertStringNotContainsString($key,$state->toJson());
    }
    public function test_first_admin_claim_closes_setup_and_reinstall_preserves_credentials(): void
    {
        $service=app(BootstrapAdmin::class); $key=$service->issue();
        $admin=$service->claim($this->data($key));
        $this->assertSame('owner',$admin->role);
        $this->assertTrue(Hash::check('Strong!Owner12345',$admin->password));
        $this->assertFalse($service->available()); $this->assertNull($service->issue());
        $this->assertNull(SetupState::find(1)->key_hash);
        $this->get('/setup')->assertNotFound();
        $this->post('/setup',$this->data($key))->assertNotFound();
        $this->assertDatabaseCount('users',1);
        $this->assertSame($admin->password,$admin->fresh()->password);
    }
    public function test_expired_and_rotated_keys_cannot_claim_an_account(): void
    {
        $service=app(BootstrapAdmin::class); $first=$service->issue(); $second=$service->issue();
        try { $service->claim($this->data($first)); $this->fail('Old key accepted'); } catch (ValidationException) {}
        $this->travel(31)->minutes();
        $this->assertFalse($service->available());
        $this->expectException(ValidationException::class); $service->claim($this->data($second));
    }
    public function test_ten_failed_attempts_invalidate_the_key_globally(): void
    {
        $service=app(BootstrapAdmin::class); $key=$service->issue();
        for($i=0;$i<10;$i++) try { $service->claim($this->data('Wrong000')); } catch (ValidationException) {}
        $this->assertFalse($service->available()); $this->assertNull(SetupState::find(1)->key_hash);
        $this->assertDatabaseCount('users',0);
        $this->expectException(ValidationException::class); $service->claim($this->data($key));
    }
    public function test_setup_remains_closed_if_an_admin_is_deleted_outside_the_application(): void
    {
        $service=app(BootstrapAdmin::class); $service->claim($this->data($service->issue()));
        User::query()->delete(); $this->assertNull($service->issue()); $this->get('/setup')->assertNotFound();
    }
    public function test_setup_is_rate_limited_and_no_public_registration_or_payment_routes_exist(): void
    {
        app(BootstrapAdmin::class)->issue();
        for($i=0;$i<5;$i++) $this->get('/setup')->assertOk();
        $this->get('/setup')->assertStatus(429);
        foreach(['/register','/admin/register','/customer','/checkout','/payments'] as $route) $this->get($route)->assertNotFound();
    }
    public function test_weak_password_does_not_create_an_admin_or_consume_a_valid_key(): void
    {
        $key=app(BootstrapAdmin::class)->issue(); $data=$this->data($key); $data['password']='weak'; $data['password_confirmation']='weak';
        $this->post('/setup',$data)->assertSessionHasErrors('password');
        $this->assertDatabaseCount('users',0); $this->assertTrue(app(BootstrapAdmin::class)->available());
    }
    public function test_setup_response_has_security_headers_and_never_contains_the_key(): void
    {
        $key=app(BootstrapAdmin::class)->issue();
        $this->get('/setup')->assertOk()->assertHeader('X-Frame-Options','DENY')->assertHeader('Referrer-Policy','no-referrer')->assertDontSee($key);
    }
    public function test_two_claims_cannot_create_two_first_admins(): void
    {
        $service=app(BootstrapAdmin::class); $key=$service->issue(); $service->claim($this->data($key));
        try { $service->claim(array_merge($this->data($key),['email'=>'attacker@example.test'])); } catch (ValidationException) {}
        $this->assertDatabaseCount('users',1);
        $this->assertDatabaseMissing('users',['email'=>'attacker@example.test']);
    }
}
