# ContextGraph Viewer

Standalone large-graph viewer for ContextGraph/FalkorDB data.

## Library Choice

This viewer uses `sigma` with `graphology` because Sigma.js is an MIT-licensed WebGL graph renderer with good interaction performance for large browser-side network graphs. Sigma renders a 2D WebGL scene, so the viewer stores deterministic `x/y/z` coordinates for every node and projects them into Sigma with perspective, depth-based size, and depth-based color shading.

For the target scale of up to 500,000 loaded nodes, the viewer avoids loading the whole database graph in one request and instead reads edge-oriented chunks from `/api/viewer/graphs/{project}/chunk`.

Why not the common alternatives:

- D3/SVG: excellent for custom charts, not viable for million-scale graph primitives.
- Cytoscape.js: strong graph analysis UI, but much heavier at this render size.
- Three.js-only graph renderers: useful for native 3D scenes, but Sigma keeps the existing admin interactions and WebGL graph pipeline simpler while still allowing a projected 3D layout.

## Run

The FastAPI app serves this folder at `/viewer`, so the local admin runtime exposes:

```text
http://localhost:8001/viewer
```

The viewer reuses the `cg_jwt` token stored by the Admin UI. Sign in at `/admin` first, then open the Graph tab or `/viewer` in the same browser session.

For frontend-only development:

```powershell
cd src/viewer
npm install
npm run dev
```

## Scale Notes

- The default display window is 250 nodes and the API caps each chunk at 500,000 nodes.
- The project picker lists only active projects whose graph stats report at least one node, so empty registered projects do not appear in the viewer.
- The primary Load action loads the requested visible node window progressively; large requests are split into 5,000-node client batches with a browser frame yielded between batches.
- The View Settings popup exposes layout relaxation controls such as repulsion strength, link distance, link strength, collision padding, Barnes-Hut theta, and relaxation limits. Settings are saved locally and can be applied to the currently loaded graph.
- Each chunk uses an internal node-id cursor and includes edges only when both endpoints are inside the selected node page.
- The client keeps the Sigma 2.5D renderer, uses a worker to precompute deterministic `x/y/z` positions, stores projection scratch data in typed arrays, and enforces a 500,000-node cap so extremely large projects do not grow the browser heap without bound.
- Batch preprocessing now runs a bounded anti-overlap relaxation pass: degree-weighted Barnes-Hut repulsion spreads hub nodes, link attraction is scaled down for high-degree endpoints, and a grid collision pass separates nodes before they reach Sigma.
- Labels are hover-only and use a high-contrast dark tooltip so node names remain readable on the dark canvas.
- Right-clicking a node focuses the graph on that node's directed downstream neighborhood; the canvas overlay slider switches between one and two loaded outgoing layers while unrelated nodes and edges stay hidden.
- The View section can show or hide each loaded node kind bucket: Repository, File, Symbol, Variable, and other Node records.
- A live FPS badge is displayed in the graph's bottom-right corner so render performance is visible while moving or rotating the graph.
- The Play/Stop control updates the projected 3D coordinates live until manually stopped. For graphs above 120,000 nodes, Play applies a single projection step per click to avoid long main-thread stalls.
- Performance mode is on by default. It adds zoom-aware node LOD, kind aggregate cluster nodes, temporary camera-motion hiding for nodes and edges, hover-neighborhood edge focus, and lighter scheduled refreshes while keeping the full 2.5D projection path available when zoomed in.
- When a loaded graph is large, zoomed-out views switch to aggregate cluster nodes for each node kind; zooming back in restores individual nodes according to the active LOD tier.
- Edges are hidden by default, and the high-volume `Uses variable` plus `Flows to` edge filters start unchecked to keep the first graph view readable. When edges are shown, performance mode throttles low-priority edges while zoomed out or rotating.
- Use edge-type filters and search before loading many chunks; 500,000 nodes plus their edges still depends on browser memory, GPU limits, and the selected edge density.
