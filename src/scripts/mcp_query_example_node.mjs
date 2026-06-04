/* Minimal MCP client example for querying ContextGraph over SSE transport.

Usage:
  set CONTEXTGRAPH_MCP_TOKEN=<project-token>
  set CONTEXTGRAPH_PROJECT_ID=<project-id>
  node src/scripts/mcp_query_example_node.mjs --base-url http://127.0.0.1:8011 --name IndexPipeline --limit 5

Requirements:
- Node.js 18+ (built-in fetch + WHATWG streams)
*/

import { randomUUID } from 'node:crypto';

function parseArgs(argv) {
  const args = {
    baseUrl: 'http://127.0.0.1:8011',
    name: 'IndexPipeline',
    limit: 5,
    token: process.env.CONTEXTGRAPH_MCP_TOKEN || '',
    projectId: process.env.CONTEXTGRAPH_PROJECT_ID || '',
  };

  for (let i = 2; i < argv.length; i += 1) {
    const cur = argv[i];
    const next = argv[i + 1];
    if (cur === '--base-url' && next) {
      args.baseUrl = next;
      i += 1;
    } else if (cur === '--name' && next) {
      args.name = next;
      i += 1;
    } else if (cur === '--limit' && next) {
      args.limit = Number.parseInt(next, 10);
      i += 1;
    } else if (cur === '--token' && next) {
      args.token = next;
      i += 1;
    } else if (cur === '--project-id' && next) {
      args.projectId = next;
      i += 1;
    }
  }
  return args;
}

function authHeaders(args) {
  const headers = {};
  if (args.token) {
    headers.Authorization = `Bearer ${args.token}`;
  }
  if (args.projectId) {
    headers['X-Project-ID'] = args.projectId;
  }
  return headers;
}

function absoluteEndpoint(baseUrl, endpoint) {
  if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
    return endpoint;
  }
  if (endpoint.startsWith('/')) {
    return `${baseUrl.replace(/\/$/, '')}${endpoint}`;
  }
  return `${baseUrl.replace(/\/$/, '')}/${endpoint}`;
}

async function readMessageEndpoint(baseUrl, headers) {
  const sseUrl = `${baseUrl.replace(/\/$/, '')}/mcp/sse`;
  const resp = await fetch(sseUrl, { method: 'GET', headers });
  if (!resp.ok || !resp.body) {
    throw new Error(`SSE connect failed: ${resp.status} ${resp.statusText}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let dataLines = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n')) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      const line = raw.replace(/\r$/, '');

      if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trim());
        continue;
      }

      if (line === '' && dataLines.length > 0) {
        const payload = dataLines.join('\n');
        dataLines = [];

        if (payload.startsWith('http://') || payload.startsWith('https://') || payload.startsWith('/')) {
          await reader.cancel();
          return absoluteEndpoint(baseUrl, payload);
        }

        try {
          const obj = JSON.parse(payload);
          for (const key of ['endpoint', 'message_endpoint', 'messages', 'url']) {
            if (typeof obj[key] === 'string') {
              await reader.cancel();
              return absoluteEndpoint(baseUrl, obj[key]);
            }
          }
        } catch {
          // ignore non-JSON frames
        }
      }
    }
  }

  throw new Error('Did not receive message endpoint from SSE stream');
}

async function rpcCall(endpoint, method, params, headers) {
  const payload = {
    jsonrpc: '2.0',
    id: randomUUID(),
    method,
    params,
  };

  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(payload),
  });

  const body = await resp.json();
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${JSON.stringify(body)}`);
  }
  if (body.error) {
    throw new Error(`MCP error: ${JSON.stringify(body.error)}`);
  }
  return body;
}

async function main() {
  const args = parseArgs(process.argv);
  const headers = authHeaders(args);
  const endpoint = await readMessageEndpoint(args.baseUrl, headers);
  console.log(`[mcp] message endpoint: ${endpoint}`);

  const result = await rpcCall(endpoint, 'tools/call', {
    name: 'find_symbol',
    arguments: {
      name: args.name,
      limit: args.limit,
    },
  }, headers);

  console.log(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
