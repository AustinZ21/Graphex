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

async function readSseEvent(reader, decoder, state) {
  while (true) {
    const newlineIndex = state.buffer.indexOf('\n');
    if (newlineIndex === -1) {
      const { done, value } = await reader.read();
      if (done) {
        throw new Error('SSE stream ended');
      }
      state.buffer += decoder.decode(value, { stream: true });
      continue;
    }

    const raw = state.buffer.slice(0, newlineIndex);
    state.buffer = state.buffer.slice(newlineIndex + 1);
    const line = raw.replace(/\r$/, '');

    if (line.startsWith('event:')) {
      state.event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      state.dataLines.push(line.slice(5).trim());
      continue;
    }
    if (line === '' && state.dataLines.length > 0) {
      const event = { event: state.event, data: state.dataLines.join('\n') };
      state.event = '';
      state.dataLines = [];
      return event;
    }
  }
}

async function readMessageEndpoint(baseUrl, headers) {
  const sseUrl = `${baseUrl.replace(/\/$/, '')}/mcp/sse`;
  const resp = await fetch(sseUrl, { method: 'GET', headers });
  if (!resp.ok || !resp.body) {
    throw new Error(`SSE connect failed: ${resp.status} ${resp.statusText}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const state = { buffer: '', dataLines: [], event: '' };
  const endpointEvent = await readSseEvent(reader, decoder, state);
  const payload = endpointEvent.data;

  if (payload.startsWith('http://') || payload.startsWith('https://') || payload.startsWith('/')) {
    return { endpoint: absoluteEndpoint(baseUrl, payload), reader, decoder, state };
  }

  const obj = JSON.parse(payload);
  for (const key of ['endpoint', 'message_endpoint', 'messages', 'url']) {
    if (typeof obj[key] === 'string') {
      return { endpoint: absoluteEndpoint(baseUrl, obj[key]), reader, decoder, state };
    }
  }
  throw new Error('Did not receive message endpoint from SSE stream');
}

async function rpcPost(endpoint, method, params, headers, id = randomUUID()) {
  const payload = { jsonrpc: '2.0', method };
  if (id) {
    payload.id = id;
  }
  if (params) {
    payload.params = params;
  }

  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
  }
  return id;
}

async function waitForRpcResponse(reader, decoder, state, id) {
  while (true) {
    const sse = await readSseEvent(reader, decoder, state);
    if (sse.event && sse.event !== 'message') {
      continue;
    }
    const body = JSON.parse(sse.data);
    if (body.id === id) {
      if (body.error) {
        throw new Error(`MCP error: ${JSON.stringify(body.error)}`);
      }
      return body;
    }
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const headers = authHeaders(args);
  const { endpoint, reader, decoder, state } = await readMessageEndpoint(args.baseUrl, headers);
  console.log(`[mcp] message endpoint: ${endpoint}`);

  try {
    const initId = await rpcPost(endpoint, 'initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'cga-node-query-example', version: '1.0' },
    }, headers, 'init-1');
    await waitForRpcResponse(reader, decoder, state, initId);

    await rpcPost(endpoint, 'notifications/initialized', {}, headers, null);

    const callId = await rpcPost(endpoint, 'tools/call', {
      name: 'find_symbol',
      arguments: {
        name: args.name,
        limit: args.limit,
      },
    }, headers);
    const result = await waitForRpcResponse(reader, decoder, state, callId);
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await reader.cancel();
  }
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});