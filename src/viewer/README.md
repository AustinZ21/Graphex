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
- The primary Load action sits immediately to the left of Load more in the Window controls.
- Each chunk uses an internal node-id cursor and includes edges only when both endpoints are inside the selected node page.
- The client renders every loaded node and edge instead of hiding lower-detail levels. It enforces a 500,000-node cap so extremely large projects do not grow the browser heap without bound.
- Labels are hover-only and use a high-contrast dark tooltip so node names remain readable on the dark canvas.
- The View section can show or hide each loaded node kind bucket: Repository, File, Symbol, Variable, and other Node records.
- A live FPS badge is displayed in the graph's bottom-right corner so render performance is visible while moving or rotating the graph.
- The 3D Rotate control updates the projected 3D coordinates live until manually stopped. For graphs above 120,000 nodes, it applies a single projection step per click to avoid long main-thread stalls.
- Edges are hidden by default, and the high-volume `Uses variable` plus `Flows to` edge filters start unchecked to keep the first graph view readable.
- Use edge-type filters and search before loading many chunks; 500,000 nodes plus their edges still depends on browser memory, GPU limits, and the selected edge density.
