# ContextGraph Viewer

Standalone large-graph viewer for ContextGraph/FalkorDB data.

## Library Choice

This viewer uses `@cosmos.gl/graph` because it is an MIT-licensed WebGL force graph renderer built for large network graphs. For the target scale of roughly 1,000,000 nodes or edges, the viewer avoids loading the whole database graph in one request and instead reads edge-oriented chunks from `/api/viewer/graphs/{project}/chunk`.

Why not the common alternatives:

- D3/SVG: excellent for custom charts, not viable for million-scale graph primitives.
- Cytoscape.js: strong graph analysis UI, but much heavier at this render size.
- G6/Sigma: useful WebGL graph libraries, but `cosmos.gl` exposes a lower-level typed-array API that fits progressive million-edge loading with less object overhead.

## Run

The FastAPI app serves this folder at `/viewer`, so the local admin runtime exposes:

```text
http://localhost:8001/viewer
```

The viewer reuses the `cg_jwt` token stored by the Admin UI. Sign in at `/admin` first, or paste a valid admin JWT into the Session Token field.

For frontend-only development:

```powershell
cd src/viewer
npm install
npm run dev
```

## Scale Notes

- The default chunk is 50,000 edges and the API caps each chunk at 100,000 edges.
- Each chunk includes all endpoint nodes required by that chunk, so edges can be appended safely.
- The client assigns dense point indices as chunks arrive, first expands newly visible nodes from the center of the final target bounds toward relationship zones, and applies zoom-based LOD so the overview renders only primary nodes and hubs before revealing symbol/detail nodes as the user zooms in.
- The center-out expansion runs before force-layout physics so the first visible movement is radial instead of a solver-driven diagonal drift. The camera is framed to the final centered bounds while nodes start at the origin, then expand outward over a visible radial phase. Simulation still runs inside the same 15-second window after the radial phase, then pauses until the user starts another run. The left control panel can be collapsed when the graph needs more viewport space, and edges can be toggled on or off without reloading the graph.
- Use edge-type filters and search before loading many chunks; rendering one million graph primitives is feasible on capable GPUs, but layout simulation cost still depends on browser memory and hardware.
