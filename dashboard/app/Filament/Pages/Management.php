<?php
namespace App\Filament\Pages;
use App\Models\{AuditEvent,Customer,Node,Plan,ProvisioningCommand,Ticket,User,VpnClient};
use App\Services\{AgentClient,NodeCollector,VpnCommands};
use Filament\Notifications\Notification;
use Filament\Pages\Page;
use Illuminate\Support\Facades\{DB,Gate,Hash,RateLimiter,Validator};
use Illuminate\Validation\Rules\Password;
use Illuminate\Validation\ValidationException;

abstract class Management extends Page
{
    protected string $view='filament.pages.management';
    protected const SECTION='clients';
    protected const LABEL='VPN users';
    public array $form=[];
    public array $command=['action'=>'add','name'=>'','days'=>30,'devices'=>1];
    public ?int $editingId=null;
    public ?int $nodeId=null;
    public string $search='';
    public string $confirmName='';
    public string $currentPassword='';
    public ?string $revealedLink=null;
    public array $backups=[];

    public function mount(): void
    {
        Gate::authorize('staff');
        abort_unless(static::canAccess(),403);
        $this->nodeId=Node::where('enabled',true)->value('id');
        $this->resetForm();
    }
    public function hydrate(): void { abort_unless(static::canAccess(),403); }
    public static function getNavigationLabel(): string { return static::LABEL; }
    public function getTitle(): string { return static::LABEL; }
    public function section(): string { return static::SECTION; }
    public static function canAccess(): bool
    {
        return Gate::allows(in_array(static::SECTION,['staff','nodes','audit'],true)?'owner':'staff');
    }
    public function resetForm(): void
    {
        $this->editingId=null;
        $this->form=['name'=>'','contact'=>'','notes'=>'','days'=>30,'ip_limit'=>1,'region'=>'Singapore',
            'active'=>true,'enabled'=>true,'socket_name'=>'','email'=>'','password'=>'','role'=>'support',
            'customer_id'=>null,'plan_id'=>null,'subject'=>'','status'=>'open'];
    }
    protected function records()
    {
        $term=mb_substr($this->search,0,100);
        return match(static::SECTION) {
            'clients'=>VpnClient::with('node')->where('node_id',$this->nodeId)->where('name','like','%'.$term.'%')->orderBy('name')->limit(200)->get(),
            'customers'=>Customer::where('name','like','%'.$term.'%')->orderBy('name')->limit(200)->get(),
            'plans'=>Plan::orderBy('name')->limit(200)->get(),
            'nodes'=>Node::orderBy('name')->get(),
            'staff'=>User::orderBy('name')->get(),
            'tickets'=>Ticket::where('subject','like','%'.$term.'%')->latest()->limit(200)->get(),
            'operations'=>ProvisioningCommand::latest()->limit(100)->get(),
            'audit'=>AuditEvent::latest('id')->limit(200)->get(),
            default=>collect(),
        };
    }
    protected function getViewData(): array
    {
        abort_unless(static::canAccess(),403);
        return ['records'=>$this->records(),'nodes'=>Node::get(),'customers'=>Customer::orderBy('name')->get(),'plans'=>Plan::where('active',true)->get()];
    }
    public function editRecord(int $id): void
    {
        Gate::authorize(static::SECTION==='tickets'?'staff':(in_array(static::SECTION,['staff','nodes'],true)?'owner':'manage-vpn'));
        $model=match(static::SECTION) {'customers'=>Customer::class,'plans'=>Plan::class,'nodes'=>Node::class,'staff'=>User::class,'tickets'=>Ticket::class,default=>null};
        abort_unless($model,403);
        $record=$model::findOrFail($id);
        $this->resetForm();
        $this->editingId=$id;
        $this->form=array_merge($this->form,array_intersect_key($record->toArray(),$this->form));
        $this->form['password']='';
    }
    public function saveRecord(): void
    {
        $section=static::SECTION;
        Gate::authorize($section==='tickets'?'staff':(in_array($section,['staff','nodes'],true)?'owner':'manage-vpn'));
        [$model,$rules]=match($section) {
            'customers'=>[Customer::class,['name'=>'required|string|max:100','contact'=>'nullable|string|max:254','notes'=>'nullable|string|max:4000']],
            'plans'=>[Plan::class,['name'=>'required|string|max:100','days'=>'required|integer|min:0|max:36500','ip_limit'=>'required|integer|min:0|max:1000','region'=>'required|string|max:80','active'=>'required|boolean']],
            'nodes'=>[Node::class,['name'=>'required|string|max:100','region'=>'required|string|max:80','socket_name'=>['required','regex:/^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/D','unique:nodes,socket_name,'.($this->editingId?:'NULL')],'enabled'=>'required|boolean']],
            'tickets'=>[Ticket::class,['customer_id'=>'nullable|exists:customers,id','subject'=>'required|string|max:200','notes'=>'required|string|max:10000','status'=>'required|in:open,in_progress,resolved']],
            'staff'=>[User::class,['name'=>'required|string|max:100','email'=>'required|email|max:254|unique:users,email,'.($this->editingId?:'NULL'),
                'role'=>'required|in:owner,operator,support','active'=>'required|boolean','password'=>[$this->editingId?'nullable':'required','string','max:128',Password::min(14)->mixedCase()->numbers()->symbols()]]],
            default=>throw new \RuntimeException('Unsupported section'),
        };
        $data=Validator::make($this->form,$rules)->validate();
        if (isset($data['email'])) $data['email']=strtolower($data['email']);
        if (empty($data['password'])) unset($data['password']);
        DB::transaction(function () use ($model,$data,$section) {
            $record=$this->editingId?$model::lockForUpdate()->findOrFail($this->editingId):new $model;
            if ($section==='staff' && $record->exists && $record->active && $record->role==='owner'
                && (!$data['active'] || $data['role']!=='owner') && User::where('active',true)->where('role','owner')->count()<=1)
                throw ValidationException::withMessages(['form.role'=>'Keep at least one active owner.']);
            $record->fill($data)->save();
            if ($section==='staff') DB::table('sessions')->where('user_id',$record->id)->delete();
            AuditEvent::write($section.'.saved',(string)$record->id,array_intersect_key($data,array_flip(['role','active'])));
        },3);
        $this->resetForm();
        Notification::make()->title('Saved')->success()->send();
    }
    public function usePlan(int $planId): void
    {
        Gate::authorize('manage-vpn');
        $plan=Plan::where('active',true)->findOrFail($planId);
        $this->command['days']=$plan->days; $this->command['devices']=$plan->ip_limit;
    }
    public function queueCommand(): void
    {
        Gate::authorize('manage-vpn');
        abort_unless(static::SECTION==='clients',403);
        if (in_array($this->command['action']??null,['remove','rotate'],true) && $this->confirmName!==($this->command['name']??''))
            throw ValidationException::withMessages(['confirmName'=>'Type the exact client name to remove or rotate its credential.']);
        app(VpnCommands::class)->submit(Node::findOrFail($this->nodeId),$this->command);
        $this->revealedLink=null; $this->confirmName='';
        Notification::make()->title('Operation queued')->body('Check Operations for the server acknowledgement.')->success()->send();
    }
    public function selectClient(int $id): void
    {
        Gate::authorize('staff');
        $client=VpnClient::where('node_id',$this->nodeId)->findOrFail($id);
        $this->command=['action'=>'extend','name'=>$client->name,'days'=>30,'devices'=>$client->ip_limit];
        $this->editingId=$client->id;
        $this->form['customer_id']=$client->customer_id; $this->form['plan_id']=$client->plan_id;
        $this->revealedLink=null;
    }
    public function saveAssignment(): void
    {
        Gate::authorize('manage-vpn');
        abort_unless(static::SECTION==='clients',403);
        $data=Validator::make($this->form,['customer_id'=>'nullable|exists:customers,id','plan_id'=>'nullable|exists:plans,id'])->validate();
        $client=VpnClient::where('node_id',$this->nodeId)->findOrFail($this->editingId);
        $client->update($data); AuditEvent::write('client.assignment',$client->name);
        Notification::make()->title('Assignment saved')->success()->send();
    }
    public function refreshNode(): void
    {
        Gate::authorize('manage-vpn');
        try { app(NodeCollector::class)->refresh(Node::findOrFail($this->nodeId)); Notification::make()->title('Server status refreshed')->success()->send(); }
        catch (\Throwable) { Notification::make()->title('Server status unavailable')->body('Cached data may be stale. Inspect the private agent.')->danger()->send(); }
    }
    public function revealLink(): void
    {
        Gate::authorize('owner');
        abort_unless(static::SECTION==='clients',403);
        $password=$this->currentPassword; $this->currentPassword='';
        if (!RateLimiter::attempt('profile-reveal:'.auth()->id(),5,fn()=>true,60)) abort(429);
        if (!Hash::check($password,auth()->user()->password)) throw ValidationException::withMessages(['currentPassword'=>'Password confirmation failed.']);
        $client=VpnClient::where('node_id',$this->nodeId)->where('name',$this->command['name']??'')->firstOrFail();
        $result=app(AgentClient::class)->request($client->node,'POST','/v1/link',['name'=>$client->name,'expected_version'=>$client->version]);
        $this->revealedLink=$result['link'];
        AuditEvent::write('credential.revealed',$client->name,['node_id'=>$client->node_id]);
    }
    public function listBackups(): void
    {
        Gate::authorize('owner');
        $result=app(AgentClient::class)->request(Node::findOrFail($this->nodeId),'GET','/v1/backups');
        $this->backups=$result['files']??[];
    }
}
