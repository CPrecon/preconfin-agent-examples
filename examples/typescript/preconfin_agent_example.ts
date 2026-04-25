declare const process: {
  env: Record<string, string | undefined>;
  exitCode?: number;
};

type JsonObject = Record<string, unknown>;

const baseUrl = (
  process.env.VITE_PRECONFIN_BASE_URL ??
  process.env.PRECONFIN_BASE_URL ??
  'https://api.preconfin.com/api'
).replace(/\/$/, '');
const agentKey = process.env.PRECONFIN_AGENT_KEY;

if (!agentKey) {
  throw new Error('PRECONFIN_AGENT_KEY is required.');
}

async function apiRequest<T>(path: string, body?: JsonObject): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: {
      Authorization: `Bearer ${agentKey}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }

  return response.json() as Promise<T>;
}

async function main(): Promise<void> {
  const tools = await apiRequest<JsonObject[]>('/agent/tools');
  console.log('Available tools:');
  console.log(JSON.stringify(tools, null, 2));

  const peopleSnapshot = await apiRequest<JsonObject>('/agent/tools/execute', {
    tool_name: 'get_people_snapshot',
    arguments: {},
  });
  console.log('\nPeople snapshot:');
  console.log(JSON.stringify(peopleSnapshot, null, 2));

  const queryResult = await apiRequest<JsonObject>('/agent/query', {
    query: 'Show recent activity',
    context: {
      source: 'stripe',
      family: 'connection',
      limit: 10,
    },
  });
  console.log('\nQuery result:');
  console.log(JSON.stringify(queryResult, null, 2));
}

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exitCode = 1;
});
