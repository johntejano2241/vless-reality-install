<?php
namespace App\Services;
use App\Models\Node;
use Illuminate\Support\Facades\Http;
use RuntimeException;

class AgentClient
{
    public function request(Node $node, string $method, string $path, array $payload = []): array
    {
        if (!$node->enabled || !preg_match('/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}$/D', $node->socket_name)) throw new RuntimeException('Node is disabled or invalid.');
        $socket = rtrim(config('admin.agent_directory'),'/').'/'.$node->socket_name.'.sock';
        $http = Http::acceptJson()->connectTimeout(3)->timeout(75)->withOptions(['curl'=>[CURLOPT_UNIX_SOCKET_PATH=>$socket]]);
        $response = $method === 'GET' ? $http->get('http://localhost'.$path) : $http->post('http://localhost'.$path, $payload);
        if ($response->status() === 409) throw new StaleOperation('Client changed. Refresh and submit a new operation.');
        if (!$response->successful() || strlen($response->body()) > 2097152 || !is_array($response->json())) throw new RuntimeException('VPN manager unavailable or invalid response.');
        return $response->json();
    }
}
