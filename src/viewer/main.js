import Graphology from 'graphology'
import Sigma from 'sigma'

const EDGE_STYLES = {
  CALLS: { label: 'Calls', color: '#4ae387', width: 1.7, priority: 6 },
  IMPORTS: { label: 'Imports', color: '#5badff', width: 1.45, priority: 5 },
  DEFINES: { label: 'Defines', color: '#ffd642', width: 1.4, priority: 4 },
  USES_VARIABLE: { label: 'Uses variable', color: '#42e694', width: 1.2, priority: 3 },
  FLOWS_TO: { label: 'Flows to', color: '#4ae387', width: 1.25, priority: 2 },
  CONTAINS: { label: 'Contains', color: '#adb8cc', width: 1.1, priority: 1 },
  UNKNOWN: { label: 'Unclassified', color: '#adb8cc', width: 1, priority: 0 },
}

const KIND_ORDER = ['Repository', 'File', 'Symbol', 'Variable', 'Node']
const KIND_INDEX = new Map(KIND_ORDER.map((kind, index) => [kind, index]))
const NODE_KIND_COLORS = { Repository: '#e06c75', File: '#61afef', Symbol: '#c678dd', Variable: '#d19a66', Node: '#7f848e' }
function kindColor(kind) { return NODE_KIND_COLORS[kind] || NODE_KIND_COLORS.Node }
const MAX_CLIENT_NODES = 500000
const MAX_CHUNK_LIMIT = 500000
const MIN_CHUNK_LIMIT = 1
const DEFAULT_CHUNK_LIMIT = 250
const DEFAULT_EDGE_VISIBILITY = false
const EDGE_VISIBILITY_STORAGE_KEY = 'cg_viewer_edges_visible_v4'
const NODE_KIND_VISIBILITY_STORAGE_KEY = 'cg_viewer_node_kinds_visible_v1'
const FPS_SAMPLE_MS = 500
const LIVE_ROTATION_NODE_LIMIT = 120000

const ROTATION_FRAME_MS = 72
const GOLDEN_ANGLE = 2.399963229728653
const BASE_DEPTH = 900
const CAMERA_DISTANCE = 3200
const BASE_NODE_SIZE = 3.6
const NODE_SIZE_STEP = 1.55
const MAX_NODE_SIZE = 18
const HOVER_LABEL_MAX_CHARS = 72
const HOVER_LABEL_FONT = '600 13px "Segoe UI", "Noto Sans", Arial, sans-serif'
const HOVER_LABEL_PADDING_X = 10
const HOVER_LABEL_HEIGHT = 28
const HOVER_LABEL_RADIUS = 6

const state = {
  graph: null,
  renderer: null,
  projectName: '',
  nextOffset: 0,
  loadedNodeIds: new Set(),
  loadedEdgeIds: new Set(),
  nodeTypes: new Map(),
  nodeDegrees: new Map(),
  nodesById: new Map(),
  loadedNodes: 0,
  loadedEdges: 0,
  skippedNodes: 0,
  skippedEdges: 0,
  hasNext: false,
  edgesVisible: DEFAULT_EDGE_VISIBILITY,
  visibleNodeKinds: new Set(KIND_ORDER),
  controlPanelCollapsed: false,
  rotationX: -0.58,
  rotationY: 0.64,
  rotationZ: 0.08,
  rotating: false,
  rotationFrame: null,
  lastRotationAt: 0,
  fpsFrame: null,
  fpsLastSampleAt: 0,
  fpsFrameCount: 0,
}

const elements = {
  workspace: document.getElementById('workspace'),
  togglePanel: document.getElementById('toggle-panel'),
  projectSelect: document.getElementById('project-select'),
  refreshProjects: document.getElementById('refresh-projects'),
  loadFirst: document.getElementById('load-first'),
  loadNext: document.getElementById('load-next'),
  clearGraph: document.getElementById('clear-graph'),
  fitView: document.getElementById('fit-view'),
  toggleSim: document.getElementById('toggle-sim'),
  toggleEdges: document.getElementById('toggle-edges'),
  nodeTypeInputs: [...document.querySelectorAll('input[name="node-type"]')],
  searchInput: document.getElementById('search-input'),
  chunkLimit: document.getElementById('chunk-limit'),
  graphRoot: document.getElementById('graph-root'),
  fpsCounter: document.getElementById('fps-counter'),
  statusLine: document.getElementById('status-line'),
  dbNodes: document.getElementById('db-nodes'),
  dbEdges: document.getElementById('db-edges'),
  loadedNodes: document.getElementById('loaded-nodes'),
  loadedEdges: document.getElementById('loaded-edges'),
  cursorValue: document.getElementById('cursor-value'),
}

function token() {
  return localStorage.getItem('cg_jwt') || ''
}

function setStatus(message, tone = 'neutral') {
  elements.statusLine.textContent = message
  elements.statusLine.dataset.tone = tone
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value || 0))
}

function edgeStyle(edgeType) {
  return EDGE_STYLES[edgeType] || EDGE_STYLES.UNKNOWN
}

function clamp(value, minValue, maxValue) {
  return Math.max(minValue, Math.min(maxValue, value))
}

const _parsedHexCache = new Map()

function parseHexColor(color) {
  let cached = _parsedHexCache.get(color)
  if (cached) return cached
  const normalized = color.replace('#', '')
  cached = {
    red: parseInt(normalized.slice(0, 2), 16),
    green: parseInt(normalized.slice(2, 4), 16),
    blue: parseInt(normalized.slice(4, 6), 16),
  }
  _parsedHexCache.set(color, cached)
  return cached
}

function toHex(channel) {
  return clamp(Math.round(channel), 0, 255).toString(16).padStart(2, '0')
}

function mixColor(sourceColor, targetColor, amount) {
  const source = parseHexColor(sourceColor)
  const target = parseHexColor(targetColor)
  return `#${toHex(source.red + (target.red - source.red) * amount)}${toHex(source.green + (target.green - source.green) * amount)}${toHex(source.blue + (target.blue - source.blue) * amount)}`
}

function depthColor(baseColor, depth) {
  const normalizedDepth = clamp((depth + 1) / 2, 0, 1)
  if (normalizedDepth >= 0.5) return mixColor(baseColor, '#f3f7ff', (normalizedDepth - 0.5) * 0.34)
  return mixColor(baseColor, '#273044', (0.5 - normalizedDepth) * 0.58)
}

function hashString(value) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function createGraph() {
  return new Graphology({ type: 'directed', multi: true, allowSelfLoops: true })
}

function ensureGraph() {
  if (!state.graph) state.graph = createGraph()
  return state.graph
}

async function api(path) {
  const headers = { Accept: 'application/json' }
  const jwt = token()
  if (jwt) headers.Authorization = `Bearer ${jwt}`
  const response = await fetch(path, { headers })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload.detail || response.statusText
    throw new Error(response.status === 401 ? `${detail}. Open Admin and sign in first.` : detail)
  }
  return payload
}

function selectedEdgeTypes() {
  return [...document.querySelectorAll('input[name="edge-type"]:checked')]
    .map((input) => input.value)
    .join(',')
}

function normalizeNodeKind(kind) {
  return KIND_INDEX.has(kind) ? kind : 'Node'
}

function selectedNodeKinds() {
  return new Set(elements.nodeTypeInputs.filter((input) => input.checked).map((input) => input.value))
}

function isNodeKindVisible(kind) {
  return state.visibleNodeKinds.has(normalizeNodeKind(kind))
}

function restoreNodeKindVisibility() {
  const storedValue = localStorage.getItem(NODE_KIND_VISIBILITY_STORAGE_KEY)
  const storedKinds = storedValue === null
    ? new Set(KIND_ORDER)
    : new Set(storedValue.split(',').filter((kind) => KIND_INDEX.has(kind)))
  elements.nodeTypeInputs.forEach((input) => {
    input.checked = storedKinds.has(input.value)
  })
  state.visibleNodeKinds = selectedNodeKinds()
}

function persistNodeKindVisibility() {
  localStorage.setItem(NODE_KIND_VISIBILITY_STORAGE_KEY, [...state.visibleNodeKinds].join(','))
}

function chunkLimit() {
  const value = Number(elements.chunkLimit.value || DEFAULT_CHUNK_LIMIT)
  return Math.max(MIN_CHUNK_LIMIT, Math.min(MAX_CHUNK_LIMIT, value))
}

function updateCounters() {
  elements.loadedNodes.textContent = formatNumber(state.loadedNodes)
  elements.loadedEdges.textContent = formatNumber(state.loadedEdges)
  elements.cursorValue.textContent = formatNumber(state.nextOffset)
}

function resizeGraphAfterPanelToggle() {
  window.setTimeout(() => {
    state.renderer?.resize?.()
    fitGraph()
  }, 220)
}

function setControlPanelCollapsed(collapsed) {
  state.controlPanelCollapsed = collapsed
  elements.workspace.classList.toggle('controls-collapsed', collapsed)
  elements.togglePanel.setAttribute('aria-label', collapsed ? 'Expand controls' : 'Collapse controls')
  elements.togglePanel.setAttribute('title', collapsed ? 'Expand controls' : 'Collapse controls')
  elements.togglePanel.setAttribute('aria-pressed', collapsed ? 'true' : 'false')
  localStorage.setItem('cg_viewer_controls_collapsed', collapsed ? '1' : '0')
  resizeGraphAfterPanelToggle()
}

function pointSizeForDegree(degree) {
  return Math.min(MAX_NODE_SIZE, BASE_NODE_SIZE + Math.log2(degree + 1) * NODE_SIZE_STEP)
}

function nodeKindIndex(kind) {
  return KIND_INDEX.get(normalizeNodeKind(kind)) ?? KIND_INDEX.get('Node')
}

function initial3dPosition(point, nodeIndex) {
  const kindIndex = nodeKindIndex(point.kind)
  const hash = hashString(point.id)
  const hashAngle = ((hash & 0xffff) / 0xffff) * Math.PI * 2
  const angle = nodeIndex * GOLDEN_ANGLE + hashAngle
  const localStep = nodeIndex > 250000 ? 2.9 : nodeIndex > 100000 ? 3.6 : 5.4
  const radius = Math.sqrt(nodeIndex + 1) * localStep + kindIndex * 240
  const layerOffset = (kindIndex - (KIND_ORDER.length - 1) / 2) * 260
  const depthNoise = (((hash >>> 16) & 0xffff) / 0xffff - 0.5) * BASE_DEPTH
  return {
    x3d: Math.cos(angle) * radius,
    y3d: Math.sin(angle) * radius,
    z3d: layerOffset + depthNoise,
  }
}

let _projCosX = Math.cos(-0.58)
let _projSinX = Math.sin(-0.58)
let _projCosY = Math.cos(0.64)
let _projSinY = Math.sin(0.64)
let _projCosZ = Math.cos(0.08)
let _projSinZ = Math.sin(0.08)
let _projRotX = -0.58
let _projRotY = 0.64
let _projRotZ = 0.08

function syncProjectionTrig() {
  if (state.rotationX !== _projRotX || state.rotationY !== _projRotY || state.rotationZ !== _projRotZ) {
    _projCosX = Math.cos(state.rotationX)
    _projSinX = Math.sin(state.rotationX)
    _projCosY = Math.cos(state.rotationY)
    _projSinY = Math.sin(state.rotationY)
    _projCosZ = Math.cos(state.rotationZ)
    _projSinZ = Math.sin(state.rotationZ)
    _projRotX = state.rotationX
    _projRotY = state.rotationY
    _projRotZ = state.rotationZ
  }
}

function project3d(x3d, y3d, z3d) {
  const yAfterX = y3d * _projCosX - z3d * _projSinX
  const zAfterX = y3d * _projSinX + z3d * _projCosX

  const xAfterY = x3d * _projCosY + zAfterX * _projSinY
  const zAfterY = -x3d * _projSinY + zAfterX * _projCosY

  const xAfterZ = xAfterY * _projCosZ - yAfterX * _projSinZ
  const yAfterZ = xAfterY * _projSinZ + yAfterX * _projCosZ

  const perspective = clamp(CAMERA_DISTANCE / Math.max(900, CAMERA_DISTANCE + zAfterY), 0.32, 2.15)
  const depth = clamp(zAfterY / BASE_DEPTH, -1, 1)
  return {
    x: xAfterZ * perspective,
    y: yAfterZ * perspective,
    depth,
    scale: perspective,
  }
}

function projectedNodeAttributes(attributes) {
  const projection = project3d(attributes.x3d || 0, attributes.y3d || 0, attributes.z3d || 0)
  const baseSize = attributes.baseSize || BASE_NODE_SIZE
  return {
    x: projection.x,
    y: projection.y,
    size: clamp(baseSize * (0.72 + projection.scale * 0.28), 1.2, MAX_NODE_SIZE + 4),
    color: depthColor(attributes.baseColor || NODE_KIND_COLORS.Node, projection.depth),
    zIndex: projection.depth,
  }
}

function truncateHoverLabel(label) {
  const value = String(label || '')
  if (value.length <= HOVER_LABEL_MAX_CHARS) return value
  return `${value.slice(0, HOVER_LABEL_MAX_CHARS - 3)}...`
}

function drawRoundedRect(context, x, y, width, height, radius) {
  const nextRadius = Math.min(radius, width / 2, height / 2)
  context.beginPath()
  context.moveTo(x + nextRadius, y)
  context.lineTo(x + width - nextRadius, y)
  context.quadraticCurveTo(x + width, y, x + width, y + nextRadius)
  context.lineTo(x + width, y + height - nextRadius)
  context.quadraticCurveTo(x + width, y + height, x + width - nextRadius, y + height)
  context.lineTo(x + nextRadius, y + height)
  context.quadraticCurveTo(x, y + height, x, y + height - nextRadius)
  context.lineTo(x, y + nextRadius)
  context.quadraticCurveTo(x, y, x + nextRadius, y)
  context.closePath()
}

function drawNodeHover(context, nodeData) {
  const label = truncateHoverLabel(nodeData.label || nodeData.rawLabel || nodeData.key)
  const nodeRadius = Math.max(nodeData.size || BASE_NODE_SIZE, BASE_NODE_SIZE)

  context.save()
  context.lineWidth = 2.25
  context.strokeStyle = '#f6fbff'
  context.fillStyle = 'rgba(255, 255, 255, 0.12)'
  context.beginPath()
  context.arc(nodeData.x, nodeData.y, nodeRadius + 4, 0, Math.PI * 2)
  context.fill()
  context.stroke()

  if (label) {
    context.font = HOVER_LABEL_FONT
    context.textBaseline = 'middle'
    context.textAlign = 'left'

    const textWidth = Math.ceil(context.measureText(label).width)
    const boxWidth = textWidth + HOVER_LABEL_PADDING_X * 2
    const boxHeight = HOVER_LABEL_HEIGHT
    const gap = nodeRadius + 10
    const canvasWidth = context.canvas.width
    const canvasHeight = context.canvas.height
    const boxX = clamp(nodeData.x + gap, 6, canvasWidth - boxWidth - 6)
    const boxY = clamp(nodeData.y - boxHeight / 2, 6, canvasHeight - boxHeight - 6)

    context.shadowColor = 'rgba(0, 0, 0, 0.45)'
    context.shadowBlur = 12
    context.shadowOffsetY = 3
    drawRoundedRect(context, boxX, boxY, boxWidth, boxHeight, HOVER_LABEL_RADIUS)
    context.fillStyle = 'rgba(11, 18, 28, 0.96)'
    context.fill()

    context.shadowColor = 'transparent'
    context.lineWidth = 1.25
    context.strokeStyle = '#75d6ff'
    context.stroke()

    context.fillStyle = '#f8fbff'
    context.fillText(label, boxX + HOVER_LABEL_PADDING_X, boxY + boxHeight / 2)
  }

  context.restore()
}

function rendererSettings() {
  return {
    allowInvalidContainer: true,
    autoCenter: true,
    autoRescale: true,
    defaultEdgeType: 'line',
    defaultNodeColor: NODE_KIND_COLORS.Node,
    defaultDrawNodeHover: drawNodeHover,
    defaultEdgeColor: '#4a5368',
    enableEdgeEvents: false,
    hideEdgesOnMove: true,
    hideLabelsOnMove: true,
    itemSizesReference: 'screen',
    labelColor: { color: '#edf1f7' },
    labelDensity: 0,
    labelFont: 'Segoe UI, Noto Sans, Arial, sans-serif',
    labelRenderedSizeThreshold: Number.POSITIVE_INFINITY,
    labelSize: 11,
    minEdgeThickness: 0.85,
    renderEdgeLabels: false,
    renderLabels: false,
    stagePadding: 28,
    zIndex: true,
  }
}

function tuneRendererForScale() {
  if (!state.renderer || !state.graph) return
  const nodeCount = state.graph.order
  state.renderer.setSettings({
    hideEdgesOnMove: nodeCount > 70000,
    hideLabelsOnMove: nodeCount > 12000,
    labelDensity: 0,
    labelRenderedSizeThreshold: Number.POSITIVE_INFINITY,
    renderLabels: false,
  })
}

function bindRendererEvents() {
  state.renderer.on('clickNode', ({ node }) => {
    const point = state.nodesById.get(node)
    if (!point) return
    const location = point.file_path ? ` - ${point.file_path}${point.line_start ? `:${point.line_start}` : ''}` : ''
    const edgeType = state.nodeTypes.get(node) || 'UNKNOWN'
    const typeLabel = edgeStyle(edgeType).label
    const degree = state.nodeDegrees.get(node) || 0
    setStatus(`${point.kind}: ${point.label}${location} (${typeLabel}, ${formatNumber(degree)} connection${degree === 1 ? '' : 's'})`, 'ok')
  })
}

function ensureRenderer() {
  const graph = ensureGraph()
  if (state.renderer) return state.renderer
  state.renderer = new Sigma(graph, elements.graphRoot, rendererSettings())
  bindRendererEvents()
  tuneRendererForScale()
  return state.renderer
}

function stopRotation() {
  if (state.rotationFrame) cancelAnimationFrame(state.rotationFrame)
  state.rotationFrame = null
  state.rotating = false
  elements.toggleSim.textContent = '3D Rotate'
}

async function destroyGraph() {
  stopRotation()
  state.renderer?.kill?.()
  state.renderer = null
  state.graph = null
  elements.graphRoot.replaceChildren()
}

function resetState() {
  state.nextOffset = 0
  state.loadedNodeIds.clear()
  state.loadedEdgeIds.clear()
  state.nodeTypes.clear()
  state.nodeDegrees.clear()
  state.nodesById.clear()
  state.loadedNodes = 0
  state.loadedEdges = 0
  state.skippedNodes = 0
  state.skippedEdges = 0
  state.hasNext = false
  state.rotationX = -0.58
  state.rotationY = 0.64
  state.rotationZ = 0.08
  stopRotation()
  elements.loadNext.disabled = true
  updateCounters()
}

function applyProjectionToAllNodes() {
  if (!state.graph || !state.graph.order) return
  syncProjectionTrig()
  state.graph.updateEachNodeAttributes(
    (_nodeId, attributes) => {
      const projection = project3d(attributes.x3d || 0, attributes.y3d || 0, attributes.z3d || 0)
      const baseSize = attributes.baseSize || BASE_NODE_SIZE
      attributes.x = projection.x
      attributes.y = projection.y
      attributes.size = clamp(baseSize * (0.72 + projection.scale * 0.28), 1.2, MAX_NODE_SIZE + 4)
      attributes.color = depthColor(attributes.baseColor || NODE_KIND_COLORS.Node, projection.depth)
      attributes.zIndex = projection.depth
      return attributes
    },
    { attributes: ['x', 'y', 'size', 'color', 'zIndex'] },
  )
  state.renderer?.refresh({ skipIndexation: false })
}

function fitGraph() {
  if (!state.renderer) return
  state.renderer.getCamera().animatedReset({ duration: 350 })
}

function updateFpsCounter(now) {
  if (!elements.fpsCounter) return
  if (!state.fpsLastSampleAt) {
    state.fpsLastSampleAt = now
    state.fpsFrameCount = 0
  } else {
    state.fpsFrameCount += 1
    const elapsed = now - state.fpsLastSampleAt
    if (elapsed >= FPS_SAMPLE_MS) {
      elements.fpsCounter.textContent = `FPS ${Math.round((state.fpsFrameCount * 1000) / elapsed)}`
      state.fpsLastSampleAt = now
      state.fpsFrameCount = 0
    }
  }
  state.fpsFrame = requestAnimationFrame(updateFpsCounter)
}

function startFpsCounter() {
  if (!elements.fpsCounter || state.fpsFrame) return
  elements.fpsCounter.textContent = 'FPS --'
  state.fpsLastSampleAt = 0
  state.fpsFrameCount = 0
  state.fpsFrame = requestAnimationFrame(updateFpsCounter)
}

function skippedSummary() {
  if (!state.skippedNodes && !state.skippedEdges) return ''
  return `${formatNumber(state.skippedNodes)} nodes and ${formatNumber(state.skippedEdges)} edges skipped after the 500,000-node cap.`
}

function statusWithSkippedSummary(message) {
  const skipped = skippedSummary()
  return skipped ? `${message} ${skipped}` : message
}

function setEdgesVisible(visible, showStatus = false) {
  state.edgesVisible = visible
  elements.toggleEdges.textContent = visible ? 'Hide Edges' : 'Show Edges'
  elements.toggleEdges.setAttribute('aria-pressed', visible ? 'true' : 'false')
  localStorage.setItem(EDGE_VISIBILITY_STORAGE_KEY, visible ? '1' : '0')
  refreshEdgeVisibility(true)
  if (showStatus) setStatus(statusWithSkippedSummary(`Edges ${visible ? 'shown' : 'hidden'}.`), 'ok')
}

function nodeIsHidden(nodeId) {
  return state.graph?.getNodeAttribute(nodeId, 'hidden') === true
}

function shouldHideEdge(attributes) {
  return !state.edgesVisible || nodeIsHidden(attributes.sourceNodeId) || nodeIsHidden(attributes.targetNodeId)
}

function refreshEdgeVisibility(skipIndexation = true) {
  if (!state.graph?.size) {
    state.renderer?.refresh({ skipIndexation })
    return
  }
  state.graph.updateEachEdgeAttributes(
    (_edgeId, attributes) => ({ ...attributes, hidden: shouldHideEdge(attributes) }),
    { attributes: ['hidden'] },
  )
  state.renderer?.refresh({ skipIndexation })
}

function setNodeKindVisibility(showStatus = false) {
  state.visibleNodeKinds = selectedNodeKinds()
  persistNodeKindVisibility()
  if (state.graph?.order) {
    state.graph.updateEachNodeAttributes(
      (_nodeId, attributes) => ({ ...attributes, hidden: !isNodeKindVisible(attributes.kind) }),
      { attributes: ['hidden'] },
    )
    refreshEdgeVisibility(false)
  }
  if (showStatus) {
    const count = state.visibleNodeKinds.size
    setStatus(statusWithSkippedSummary(`${formatNumber(count)} node type${count === 1 ? '' : 's'} visible.`), 'ok')
  }
}

function incrementNodeDegree(nodeId) {
  const degree = (state.nodeDegrees.get(nodeId) || 0) + 1
  state.nodeDegrees.set(nodeId, degree)
  return degree
}

function assignNodeType(nodeId, edgeType) {
  const currentType = state.nodeTypes.get(nodeId)
  if (currentType && edgeStyle(currentType).priority >= edgeStyle(edgeType).priority) return
  state.nodeTypes.set(nodeId, edgeType)
}

function updateNodeStyle(nodeId) {
  if (!state.graph?.hasNode(nodeId)) return
  const degree = state.nodeDegrees.get(nodeId) || 0
  const attributes = state.graph.getNodeAttributes(nodeId)
  const nextAttributes = {
    ...attributes,
    baseColor: kindColor(attributes.kind),
    baseSize: pointSizeForDegree(degree),
  }
  state.graph.replaceNodeAttributes(nodeId, {
    ...nextAttributes,
    ...projectedNodeAttributes(nextAttributes),
  })
}

function addPoint(point) {
  const graph = ensureGraph()
  if (graph.hasNode(point.id)) return false
  if (graph.order >= MAX_CLIENT_NODES) {
    state.skippedNodes += 1
    return false
  }

  const nodeIndex = graph.order
  const position = initial3dPosition(point, nodeIndex)
  const baseAttributes = {
    ...position,
    baseColor: kindColor(point.kind),
    baseSize: pointSizeForDegree(0),
    forceLabel: false,
    hidden: !isNodeKindVisible(point.kind),
    kind: point.kind,
    label: point.label,
    rawLabel: point.label,
    subtitle: point.subtitle,
  }
  graph.addNode(point.id, {
    ...baseAttributes,
    ...projectedNodeAttributes(baseAttributes),
  })
  state.loadedNodeIds.add(point.id)
  state.nodesById.set(point.id, point)
  return true
}

function addLink(link, dirtyNodes) {
  const graph = ensureGraph()
  if (state.loadedEdgeIds.has(link.id)) return false
  if (!graph.hasNode(link.source) || !graph.hasNode(link.target)) {
    state.skippedEdges += 1
    return false
  }

  const style = edgeStyle(link.type)
  const edgeAttributes = {
    color: style.color,
    edgeType: link.type,
    label: style.label,
    size: style.width,
    sourceNodeId: link.source,
    targetNodeId: link.target,
    type: 'line',
  }
  graph.addDirectedEdgeWithKey(link.id, link.source, link.target, {
    ...edgeAttributes,
    hidden: shouldHideEdge(edgeAttributes),
  })
  state.loadedEdgeIds.add(link.id)
  assignNodeType(link.source, link.type)
  assignNodeType(link.target, link.type)
  incrementNodeDegree(link.source)
  incrementNodeDegree(link.target)
  dirtyNodes.add(link.source)
  dirtyNodes.add(link.target)
  return true
}

function appendBatchToGraph(batch) {
  let addedNodes = 0
  let addedEdges = 0
  const dirtyNodes = new Set()

  syncProjectionTrig()

  for (const point of batch.points) {
    if (addPoint(point)) addedNodes += 1
  }
  for (const link of batch.links) {
    if (addLink(link, dirtyNodes)) addedEdges += 1
  }

  for (const nodeId of dirtyNodes) {
    updateNodeStyle(nodeId)
  }

  ensureRenderer()
  tuneRendererForScale()
  state.renderer.refresh({ skipIndexation: false })
  state.loadedNodes = state.graph.order
  state.loadedEdges = state.graph.size
  return { addedNodes, addedEdges }
}

function stepRotation(deltaX, deltaY, deltaZ) {
  state.rotationX += deltaX
  state.rotationY += deltaY
  state.rotationZ += deltaZ
  applyProjectionToAllNodes()
}

function rotateFrame(now) {
  if (!state.rotating) return
  if (now - state.lastRotationAt >= ROTATION_FRAME_MS) {
    state.lastRotationAt = now
    stepRotation(0.004, 0.012, 0.002)
  }
  state.rotationFrame = requestAnimationFrame(rotateFrame)
}

function startRotationWindow(showStatus = false) {
  if (!state.graph?.order) return
  if (state.graph.order > LIVE_ROTATION_NODE_LIMIT) {
    stepRotation(0.08, 0.18, 0.03)
    setStatus(statusWithSkippedSummary('Applied one 3D projection step for the large graph.'), 'ok')
    return
  }
  stopRotation()
  state.rotating = true
  state.lastRotationAt = 0
  elements.toggleSim.textContent = 'Stop'
  if (showStatus) setStatus('Rotating the 3D projection...', 'ok')
  state.rotationFrame = requestAnimationFrame(rotateFrame)
}

async function appendBatch(batch, reset) {
  if (reset) await destroyGraph()
  const normalized = appendBatchToGraph(batch)
  state.hasNext = batch.next_offset !== null && state.loadedNodes < MAX_CLIENT_NODES
  state.nextOffset = batch.next_offset ?? (batch.offset + batch.points.length)
  elements.loadNext.disabled = !state.hasNext
  updateCounters()
  if (reset || normalized.addedNodes) fitGraph()
  return normalized
}

async function loadStats(projectName) {
  const stats = await api(`/api/viewer/graphs/${encodeURIComponent(projectName)}/stats`)
  elements.dbNodes.textContent = formatNumber(stats.total_nodes)
  elements.dbEdges.textContent = formatNumber(stats.total_edges)
  if (stats.max_chunk_limit) {
    elements.chunkLimit.max = String(Math.min(MAX_CHUNK_LIMIT, stats.max_chunk_limit))
  }
}

async function loadChunk(reset = false) {
  const projectName = elements.projectSelect.value
  if (!projectName) {
    setStatus('Select a project first.', 'warn')
    return
  }
  state.projectName = projectName
  const offset = reset ? 0 : state.nextOffset
  const edgeTypes = selectedEdgeTypes()
  if (!edgeTypes) {
    setStatus('Select at least one edge type.', 'warn')
    return
  }
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(chunkLimit()),
    edge_types: edgeTypes,
  })
  const search = elements.searchInput.value.trim()
  if (search) params.set('search', search)

  elements.loadFirst.disabled = true
  elements.loadNext.disabled = true
  setStatus(`Loading ${formatNumber(chunkLimit())} nodes from ${projectName}...`)
  try {
    if (reset) {
      resetState()
      await loadStats(projectName)
    }
    const batch = await api(`/api/viewer/graphs/${encodeURIComponent(projectName)}/chunk?${params}`)
    const normalized = await appendBatch(batch, reset)
    const more = state.loadedNodes >= MAX_CLIENT_NODES
      ? 'The 500,000-node client cap has been reached.'
      : batch.next_offset === null ? 'No more chunks for this filter.' : 'Ready for the next chunk.'
    setStatus(statusWithSkippedSummary(`Loaded ${formatNumber(normalized.addedNodes)} nodes and ${formatNumber(normalized.addedEdges)} edges. ${more}`), 'ok')
  } catch (error) {
    setStatus(error.message, 'error')
  } finally {
    elements.loadFirst.disabled = false
    if (state.hasNext && state.renderer) elements.loadNext.disabled = false
  }
}

async function loadProjects() {
  setStatus('Loading projects...')
  try {
    const projects = await api('/api/auth/projects')
    const activeProjects = projects.filter((project) => project.is_active)
    elements.projectSelect.replaceChildren(
      ...activeProjects.map((project) => {
        const option = document.createElement('option')
        option.value = project.project_name
        option.textContent = project.project_name
        return option
      }),
    )
    if (activeProjects.length) {
      await loadStats(activeProjects[0].project_name)
      setStatus('Select a graph window and load a chunk.', 'ok')
    } else {
      setStatus('No active projects are registered.', 'warn')
    }
  } catch (error) {
    setStatus(error.message, 'error')
  }
}

function wireEvents() {
  elements.togglePanel.addEventListener('click', () => setControlPanelCollapsed(!state.controlPanelCollapsed))
  elements.refreshProjects.addEventListener('click', loadProjects)
  elements.loadFirst.addEventListener('click', () => loadChunk(true))
  elements.loadNext.addEventListener('click', () => loadChunk(false))
  elements.clearGraph.addEventListener('click', async () => {
    await destroyGraph()
    resetState()
    setStatus('Graph cleared.', 'ok')
  })
  elements.fitView.addEventListener('click', fitGraph)
  elements.toggleEdges.addEventListener('click', () => setEdgesVisible(!state.edgesVisible, true))
  elements.nodeTypeInputs.forEach((input) => input.addEventListener('change', () => setNodeKindVisibility(true)))
  elements.toggleSim.addEventListener('click', () => {
    if (!state.graph) return
    if (state.rotating) stopRotation()
    else startRotationWindow(true)
  })
  elements.projectSelect.addEventListener('change', async () => {
    if (elements.projectSelect.value) await loadStats(elements.projectSelect.value)
  })
}

async function boot() {
  elements.chunkLimit.max = String(MAX_CHUNK_LIMIT)
  if (Number(elements.chunkLimit.value) > MAX_CHUNK_LIMIT) elements.chunkLimit.value = String(DEFAULT_CHUNK_LIMIT)
  setControlPanelCollapsed(localStorage.getItem('cg_viewer_controls_collapsed') === '1')
  restoreNodeKindVisibility()
  const storedEdgeVisibility = localStorage.getItem(EDGE_VISIBILITY_STORAGE_KEY)
  setEdgesVisible(storedEdgeVisibility === null ? DEFAULT_EDGE_VISIBILITY : storedEdgeVisibility === '1')
  startFpsCounter()
  wireEvents()
  await loadProjects()
}

boot().catch((error) => setStatus(error.message, 'error'))
