<x-filament-panels::page>
    <style>.esmi-console{display:grid;gap:1.5rem}.esmi-console table{border-collapse:collapse;width:100%}.esmi-console td,.esmi-console th{padding:.85rem;text-align:left;border-bottom:1px solid #94a3b833}.esmi-console label{display:block;font-size:.9rem}.esmi-console input:not([type=checkbox]),.esmi-console select,.esmi-console textarea{display:block;width:100%;padding:.6rem .75rem;margin-top:.4rem;border:1px solid #94a3b866;border-radius:.6rem;background:transparent;color:inherit}.esmi-console .grid{display:grid;gap:1rem}.esmi-console .flex{display:flex;flex-wrap:wrap;gap:.75rem}.esmi-console p{line-height:1.65}.esmi-console .mt-3{margin-top:.75rem}.esmi-console .mt-4{margin-top:1rem}.esmi-console .mt-5{margin-top:1.25rem}.esmi-console .overflow-x-auto{overflow-x:auto}.esmi-console .text-amber-600{color:#d97706}.esmi-console .text-red-600{color:#dc2626}.esmi-console .break-all{overflow-wrap:anywhere}@media(min-width:768px){.esmi-console .md\:grid-cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.esmi-console .md\:grid-cols-3{grid-template-columns:repeat(3,minmax(0,1fr))}.esmi-console .md\:col-span-2{grid-column:span 2}}</style>
    <div wire:poll.15s class="esmi-console space-y-6">
        <x-filament::section>
            <p class="text-sm text-gray-500">Administrator workspace · status is collected from the private VPN manager. Account changes can briefly reconnect users on that node.</p>
            @if(in_array($this->section(),['clients','operations','nodes']))
                <div class="mt-4 flex flex-wrap items-center gap-3">
                    <label>Server <select wire:model.live="nodeId" class="rounded-lg border-gray-300 dark:bg-gray-900">@foreach($nodes as $node)<option value="{{ $node->id }}">{{ $node->name }}</option>@endforeach</select></label>
                    @can('manage-vpn')<x-filament::button wire:click="refreshNode" wire:loading.attr="disabled">Refresh server status</x-filament::button>@endcan
                </div>
                @foreach($nodes as $node)
                    @if($node->id===$nodeId)
                        <p class="mt-3 text-sm">Last sample: {{ $node->observed_at?->timezone('Asia/Manila')->format('Y-m-d H:i:s').' PHT' ?? 'Never collected' }}</p>
                        @if($node->error || !$node->observed_at || $node->observed_at->lt(now()->subMinutes(3)))<p class="mt-2 text-amber-600" role="alert">Server data is stale or unavailable. {{ $node->error }}</p>@endif
                        @if($node->health['statistics_error']??false)<p class="text-amber-600">Online IPs and traffic statistics are unavailable.</p>@endif
                    @endif
                @endforeach
            @endif
            <label class="mt-4 block">Search <input wire:model.live.debounce.400ms="search" maxlength="100" class="rounded-lg border-gray-300 dark:bg-gray-900" placeholder="Name or subject"></label>
        </x-filament::section>

        @if($errors->any())<x-filament::section><p class="text-red-600" role="alert">{{ $errors->first() }}</p></x-filament::section>@endif

        <x-filament::section>
            <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr class="border-b">
                @if($this->section()==='clients')<th class="p-3">VPN account</th><th>Status</th><th>Expiry (PHT)</th><th>IP slots</th><th>Online IPs</th><th>Aggregate traffic</th><th></th>
                @elseif($this->section()==='audit')<th class="p-3">When</th><th>Actor ID</th><th>Action</th><th>Target</th>
                @elseif($this->section()==='operations')<th class="p-3">When</th><th>Account</th><th>Action</th><th>State</th><th>Details</th>
                @elseif($this->section()==='nodes')<th class="p-3">Server</th><th>Region</th><th>Socket</th><th>Services</th><th></th>
                @elseif($this->section()==='staff')<th class="p-3">Name</th><th>Email</th><th>Role</th><th>Active</th><th></th>
                @elseif($this->section()==='plans')<th class="p-3">Plan</th><th>Days</th><th>IP slots</th><th>Region</th><th></th>
                @elseif($this->section()==='tickets')<th class="p-3">Subject</th><th>Status</th><th>Notes</th><th></th>
                @else<th class="p-3">Name</th><th>Contact</th><th>Notes</th><th></th>@endif
            </tr></thead><tbody>
            @forelse($records as $record)<tr class="border-b" wire:key="{{ $this->section() }}-{{ $record->id }}">
                @if($this->section()==='clients')
                    <td class="p-3 font-medium">{{ $record->name }}</td><td>{{ ucfirst($record->status) }}</td><td>{{ $record->expires_at?->timezone('Asia/Manila')->format('Y-m-d H:i').' PHT' ?? 'No expiry' }}</td><td>{{ $record->ip_limit ?: 'Unlimited' }}</td><td>{{ $record->online_ips===null ? 'Unknown' : implode(', ',$record->online_ips) ?: 'None' }}</td><td>{{ number_format(($record->upload_bytes+$record->download_bytes)/1073741824,2) }} GiB</td><td><x-filament::button size="sm" wire:click="selectClient({{ $record->id }})">Select</x-filament::button></td>
                @elseif($this->section()==='audit')<td class="p-3">{{ $record->created_at }}</td><td>{{ $record->actor_id ?? 'System' }}</td><td>{{ $record->action }}</td><td>{{ $record->target }}</td>
                @elseif($this->section()==='operations')<td class="p-3">{{ $record->created_at }}</td><td>{{ $record->client_name }}</td><td>{{ $record->action }}</td><td>{{ $record->state }}</td><td>{{ $record->error }}</td>
                @elseif($this->section()==='nodes')<td class="p-3">{{ $record->name }}</td><td>{{ $record->region }}</td><td>{{ $record->socket_name }}.sock</td><td>{{ $record->error ?? json_encode($record->health['services']??['status'=>'Unknown']) }}</td><td><x-filament::button size="sm" wire:click="editRecord({{ $record->id }})">Edit</x-filament::button></td>
                @elseif($this->section()==='staff')<td class="p-3">{{ $record->name }}</td><td>{{ $record->email }}</td><td>{{ $record->role }}</td><td>{{ $record->active?'Yes':'No' }}</td><td><x-filament::button size="sm" wire:click="editRecord({{ $record->id }})">Edit</x-filament::button></td>
                @elseif($this->section()==='plans')<td class="p-3">{{ $record->name }}</td><td>{{ $record->days ?: 'No expiry' }}</td><td>{{ $record->ip_limit ?: 'Unlimited' }}</td><td>{{ $record->region }}</td><td>@can('manage-vpn')<x-filament::button size="sm" wire:click="editRecord({{ $record->id }})">Edit</x-filament::button>@endcan</td>
                @elseif($this->section()==='tickets')<td class="p-3">{{ $record->subject }}</td><td>{{ $record->status }}</td><td class="max-w-md truncate">{{ $record->notes }}</td><td><x-filament::button size="sm" wire:click="editRecord({{ $record->id }})">Edit</x-filament::button></td>
                @else<td class="p-3">{{ $record->name }}</td><td>{{ $record->contact }}</td><td class="max-w-md truncate">{{ $record->notes }}</td><td>@can('manage-vpn')<x-filament::button size="sm" wire:click="editRecord({{ $record->id }})">Edit</x-filament::button>@endcan</td>@endif
            </tr>@empty<tr><td colspan="7" class="p-6 text-gray-500">No records. Use Refresh server status to import existing VPN accounts.</td></tr>@endforelse
            </tbody></table></div>
            <p class="mt-3 text-xs text-gray-500">Showing up to {{ $this->section()==='operations'?100:200 }} records. IP slots count public addresses; phones on the same Wi-Fi may share one slot. Traffic is collected usage, not a hard quota.</p>
        </x-filament::section>

        @if($this->section()==='clients')
            @can('manage-vpn')<x-filament::section heading="Manage VPN access">
                <form wire:submit="queueCommand" class="grid gap-4 md:grid-cols-2">
                    <label>Operation<select wire:model.live="command.action" class="block w-full rounded-lg dark:bg-gray-900">@foreach(['add'=>'Add account','extend'=>'Extend / set no expiry','suspend'=>'Suspend','resume'=>'Resume','set-limit'=>'Set public-IP slots','rotate'=>'Rotate credential','remove'=>'Permanently remove'] as $value=>$label)<option value="{{ $value }}">{{ $label }}</option>@endforeach</select></label>
                    <label>Client name<input wire:model="command.name" maxlength="48" required class="block w-full rounded-lg dark:bg-gray-900"></label>
                    <label>Days (0 = no expiry)<input type="number" wire:model="command.days" min="0" max="36500" required class="block w-full rounded-lg dark:bg-gray-900"></label>
                    <label>Public-IP slots (0 = unlimited)<input type="number" wire:model="command.devices" min="0" max="1000" required class="block w-full rounded-lg dark:bg-gray-900"></label>
                    <label>Apply plan defaults<select wire:change="usePlan($event.target.value)" class="block w-full rounded-lg dark:bg-gray-900"><option value="">Choose a plan</option>@foreach($plans as $plan)<option value="{{ $plan->id }}">{{ $plan->name }}</option>@endforeach</select></label>
                    @if(in_array($command['action'],['rotate','remove']))<label>Confirm exact client name<input wire:model="confirmName" required class="block w-full rounded-lg dark:bg-gray-900"></label>@endif
                    <x-filament::button type="submit" wire:loading.attr="disabled" wire:confirm="Apply this access change? Connected users on this node may briefly reconnect.">Queue access change</x-filament::button>
                </form>
                <p class="mt-3 text-sm text-gray-500">Extensions preserve the credential and extend a finite expiry from its current end. Suspension remains in effect until an explicit resume. Rotation invalidates the old link.</p>
                @if($editingId)<form wire:submit="saveAssignment" class="mt-5 grid gap-3 md:grid-cols-3"><label>Customer<select wire:model="form.customer_id" class="block w-full rounded-lg dark:bg-gray-900"><option value="">Unassigned</option>@foreach($customers as $customer)<option value="{{ $customer->id }}">{{ $customer->name }}</option>@endforeach</select></label><label>Plan label<select wire:model="form.plan_id" class="block w-full rounded-lg dark:bg-gray-900"><option value="">Unassigned</option>@foreach($plans as $plan)<option value="{{ $plan->id }}">{{ $plan->name }}</option>@endforeach</select></label><x-filament::button type="submit">Save assignment</x-filament::button></form>@endif
            </x-filament::section>@endcan
            @can('owner')<x-filament::section heading="Reveal selected account link"><form wire:submit="revealLink" class="flex flex-wrap gap-3"><input type="password" wire:model="currentPassword" autocomplete="current-password" placeholder="Confirm your admin password" required class="rounded-lg dark:bg-gray-900"><x-filament::button type="submit">Reveal private link</x-filament::button></form>@if($revealedLink)<p class="mt-4 break-all font-mono text-sm">{{ $revealedLink }}</p><x-filament::button size="sm" wire:click="$set('revealedLink',null)">Hide link</x-filament::button>@endif</x-filament::section>@endcan
        @elseif(in_array($this->section(),['customers','plans','nodes','staff','tickets']))
            @if($this->section()==='tickets' || Gate::allows(in_array($this->section(),['staff','nodes'])?'owner':'manage-vpn'))
            <x-filament::section :heading="$editingId ? 'Edit record' : 'Add record'">
                <form wire:submit="saveRecord" class="grid gap-4 md:grid-cols-2">
                    @if($this->section()==='tickets')<label>Subject<input wire:model="form.subject" required maxlength="200" class="block w-full rounded-lg dark:bg-gray-900"></label><label>Status<select wire:model="form.status" class="block w-full rounded-lg dark:bg-gray-900"><option value="open">Open</option><option value="in_progress">In progress</option><option value="resolved">Resolved</option></select></label>
                    @else<label>Name<input wire:model="form.name" required maxlength="100" class="block w-full rounded-lg dark:bg-gray-900"></label>@endif
                    @if($this->section()==='customers')<label>Contact<input wire:model="form.contact" maxlength="254" class="block w-full rounded-lg dark:bg-gray-900"></label>@endif
                    @if(in_array($this->section(),['customers','tickets']))<label class="md:col-span-2">Notes<textarea wire:model="form.notes" rows="4" maxlength="10000" class="block w-full rounded-lg dark:bg-gray-900"></textarea></label>@endif
                    @if($this->section()==='tickets')<label>Customer<select wire:model="form.customer_id" class="block w-full rounded-lg dark:bg-gray-900"><option value="">Unassigned</option>@foreach($customers as $customer)<option value="{{ $customer->id }}">{{ $customer->name }}</option>@endforeach</select></label>@endif
                    @if(in_array($this->section(),['plans','nodes']))<label>Region<input wire:model="form.region" required maxlength="80" class="block w-full rounded-lg dark:bg-gray-900"></label>@endif
                    @if($this->section()==='plans')<label>Days (0 = no expiry)<input type="number" wire:model="form.days" min="0" max="36500" required class="block w-full rounded-lg dark:bg-gray-900"></label><label>Public-IP slots<input type="number" wire:model="form.ip_limit" min="0" max="1000" required class="block w-full rounded-lg dark:bg-gray-900"></label><label><input type="checkbox" wire:model="form.active"> Available for assignment</label>@endif
                    @if($this->section()==='nodes')<label>Private socket name<input wire:model="form.socket_name" required maxlength="48" class="block w-full rounded-lg dark:bg-gray-900"><span class="text-xs">Server operator must provision this Unix socket first.</span></label><label><input type="checkbox" wire:model="form.enabled"> Enabled</label>@endif
                    @if($this->section()==='staff')<label>Email<input type="email" wire:model="form.email" required class="block w-full rounded-lg dark:bg-gray-900"></label><label>Role<select wire:model="form.role" class="block w-full rounded-lg dark:bg-gray-900"><option value="owner">Owner</option><option value="operator">VPN operator</option><option value="support">Support</option></select></label><label>New password<input type="password" wire:model="form.password" minlength="14" maxlength="128" autocomplete="new-password" class="block w-full rounded-lg dark:bg-gray-900"><span class="text-xs">14+ characters; leave blank on edit to keep the password.</span></label><label><input type="checkbox" wire:model="form.active"> Active staff account</label>@endif
                    <div class="flex gap-3"><x-filament::button type="submit" wire:loading.attr="disabled">Save record</x-filament::button><x-filament::button color="gray" wire:click="resetForm">Clear form</x-filament::button></div>
                </form>
            </x-filament::section>@endif
        @endif

        @if($this->section()==='operations')@can('owner')<x-filament::section heading="Recovery and backups"><p class="text-sm text-gray-500">Encrypted backups run on the server daily. Restore and off-host transfer require the server operator; this web app cannot download private server files.</p><x-filament::button class="mt-3" wire:click="listBackups">List encrypted backups on selected server</x-filament::button><ul class="mt-3 text-sm">@foreach($backups as $backup)<li>{{ $backup }}</li>@endforeach</ul></x-filament::section>@endcan @endif
    </div>
</x-filament-panels::page>
