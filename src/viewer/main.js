import { Graph } from '@cosmos.gl/graph'

const state = {
  graph: null,
  projectName: '',
  nextOffset: 0,
  pointIndexById: new Map(),
  pointTypeById: new Map(),
  pointsByIndex: [],
  pointDegrees: [],
  layoutZoneCounts: new Map(),
  loadedLinkIds: new Set(),
  pointPositions: [],
  pointTargetPositions: [],
  pointColors: [],
  pointSizes: [],
  linkPairs: [],
  linkColors: [],
  linkTypes: [],
  linkWidths: [],
  visibleToFullPointIndex: [],
  visibleNodes: 0,
  visibleEdges: 0,
  lodLevel: 1,
  zoomLevel: 1,
  lodFrame: null,
  radialAnimationFrame: null,
  pendingRadialPointIndexes: new Set(),
  controlPanelCollapsed: false,
  edgesVisible: true,
  loadedNodes: 0,
  loadedEdges: 0,
  hasNext: false,
  paused: true,
  simulationTimer: null,
}

const EDGE_STYLES = {
  CALLS: { label: 'Calls', color: [1, 0.36, 0.39, 1], width: 1.65, priority: 6 },
  IMPORTS: { label: 'Imports', color: [0.36, 0.67, 1, 1], width: 1.45, priority: 5 },
  DEFINES: { label: 'Defines', color: [1, 0.84, 0.26, 1], width: 1.4, priority: 4 },
  USES_VARIABLE: { label: 'Uses variable', color: [0.26, 0.9, 0.58, 1], width: 1.3, priority: 3 },
  FLOWS_TO: { label: 'Flows to', color: [1, 0.55, 0.25, 1], width: 1.35, priority: 2 },
  CONTAINS: { label: 'Contains', color: [0.68, 0.5, 1, 1], width: 1.1, priority: 1 },
  UNKNOWN: { label: 'Unclassified', color: [0.68, 0.72, 0.8, 1], width: 1, priority: 0 },
}

const POINT_ALPHA = 0.96
const LINK_ALPHA = 0.78
const POINT_BASE_SIZE = 4.6
const POINT_SIZE_STEP = 2.1
const POINT_MAX_SIZE = 22
const SIMULATION_RUN_MS = 15000
const RADIAL_ANIMATION_MS = 4200
const GOLDEN_ANGLE = 2.399963229728653
const LOD_HUB_DEGREE_MIN = 4
const LOD_SYMBOL_DEGREE_MIN = 2
const LOD_ZOOM_THRESHOLDS = [1.45, 2.75]
const LAYOUT_ZONE_ORDER = ['CALLS', 'IMPORTS', 'DEFINES', 'CONTAINS', 'USES_VARIABLE', 'FLOWS_TO', 'UNKNOWN']
const LAYOUT_ZONE_INDEX = new Map(LAYOUT_ZONE_ORDER.map((edgeType, index) => [edgeType, index]))

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
  searchInput: document.getElementById('search-input'),
  chunkLimit: document.getElementById('chunk-limit'),
  tokenInput: document.getElementById('token-input'),
  saveToken: document.getElementById('save-token'),
  forgetToken: document.getElementById('forget-token'),
  graphRoot: document.getElementById('graph-root'),
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

function edgeColor(edgeType, alpha = 1) {
  const [red, green, blue] = edgeStyle(edgeType).color
  return [red, green, blue, alpha]
}

function pushColor(target, color) {
  target.push(color[0], color[1], color[2], color[3])
}

function setPointColor(pointIndex, edgeType) {
  const color = edgeColor(edgeType, POINT_ALPHA)
  const offset = pointIndex * 4
  state.pointColors[offset] = color[0]
  state.pointColors[offset + 1] = color[1]
  state.pointColors[offset + 2] = color[2]
  state.pointColors[offset + 3] = color[3]
}

function pointSizeForDegree(degree) {
  return Math.min(POINT_MAX_SIZE, POINT_BASE_SIZE + Math.log2(degree + 1) * POINT_SIZE_STEP)
}

function incrementPointDegree(pointIndex) {
  const degree = (state.pointDegrees[pointIndex] || 0) + 1
  state.pointDegrees[pointIndex] = degree
  state.pointSizes[pointIndex] = pointSizeForDegree(degree)
}

function clearSimulationTimer() {
  if (!state.simulationTimer) return
  clearTimeout(state.simulationTimer)
  state.simulationTimer = null
}

function cancelRadialAnimation() {
  if (!state.radialAnimationFrame) return
  cancelAnimationFrame(state.radialAnimationFrame)
  state.radialAnimationFrame = null
}

function pauseSimulation(auto = false) {
  clearSimulationTimer()
  cancelRadialAnimation()
  state.graph?.pause?.()
  state.paused = true
  elements.toggleSim.textContent = 'Run'
  if (auto) setStatus('Simulation paused after 15 seconds. Press Run to continue.', 'ok')
}

function startSimulationWindow(showStatus = false) {
  if (!state.graph) return
  clearSimulationTimer()
  cancelRadialAnimation()
  state.graph.unpause?.()
  state.paused = false
  elements.toggleSim.textContent = 'Pause'
  if (showStatus) setStatus('Simulation running for 15 seconds...', 'ok')
  state.simulationTimer = setTimeout(() => pauseSimulation(true), SIMULATION_RUN_MS)
}

function assignPointType(pointId, edgeType) {
  const pointIndex = state.pointIndexById.get(pointId)
  if (pointIndex === undefined) return
  const currentType = state.pointTypeById.get(pointId)
  if (currentType && edgeStyle(currentType).priority >= edgeStyle(edgeType).priority) return
  state.pointTypeById.set(pointId, edgeType)
  setPointColor(pointIndex, edgeType)
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

function chunkLimit() {
  const value = Number(elements.chunkLimit.value || 50000)
  return Math.max(1000, Math.min(100000, value))
}

function resetState() {
  state.nextOffset = 0
  state.pointIndexById.clear()
  state.pointTypeById.clear()
  state.pointsByIndex = []
  state.pointDegrees = []
  state.layoutZoneCounts.clear()
  state.loadedLinkIds.clear()
  state.pointPositions = []
  state.pointTargetPositions = []
  state.pointColors = []
  state.pointSizes = []
  state.linkPairs = []
  state.linkColors = []
  state.linkTypes = []
  state.linkWidths = []
  state.visibleToFullPointIndex = []
  state.visibleNodes = 0
  state.visibleEdges = 0
  state.lodLevel = 1
  state.zoomLevel = 1
  if (state.lodFrame) cancelAnimationFrame(state.lodFrame)
  state.lodFrame = null
  cancelRadialAnimation()
  state.pendingRadialPointIndexes.clear()
  state.loadedNodes = 0
  state.loadedEdges = 0
  state.hasNext = false
  pauseSimulation()
  elements.loadNext.disabled = true
  updateCounters()
}

function updateCounters() {
  elements.loadedNodes.textContent = formatNumber(state.loadedNodes)
  elements.loadedEdges.textContent = formatNumber(state.loadedEdges)
  elements.cursorValue.textContent = formatNumber(state.nextOffset)
}

function resizeGraphAfterPanelToggle() {
  window.setTimeout(() => state.graph?.fitView?.(350, 0.12), 220)
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

function setEdgesVisible(visible, showStatus = false) {
  state.edgesVisible = visible
  elements.toggleEdges.textContent = visible ? 'Hide Edges' : 'Show Edges'
  elements.toggleEdges.setAttribute('aria-pressed', visible ? 'true' : 'false')
  localStorage.setItem('cg_viewer_edges_visible', visible ? '1' : '0')
  if (state.graph) syncGraphBuffers()
  if (showStatus) {
    const visibility = visible ? 'shown' : 'hidden'
    setStatus(`Edges ${visibility}. ${lodSummary()}`, 'ok')
  }
}

async function destroyGraph() {
  clearSimulationTimer()
  cancelRadialAnimation()
  if (state.graph) {
    state.graph.destroy?.()
    state.graph = null
  }
  state.paused = true
  elements.toggleSim.textContent = 'Run'
  elements.graphRoot.replaceChildren()
}

function graphConfig() {
  return {
    spaceSize: 16384,
    backgroundColor: '#151922',
    pointDefaultColor: edgeColor('UNKNOWN', POINT_ALPHA),
    linkDefaultColor: edgeColor('UNKNOWN', LINK_ALPHA),
    curvedLinks: true,
    fitViewOnInit: false,
    fitViewDelay: 0,
    fitViewPadding: 0.18,
    rescalePositions: false,
    enableDrag: true,
    pointDefaultSize: POINT_BASE_SIZE,
    linkDefaultWidth: 1.15,
    linkOpacity: 0.95,
    renderHoveredPointRing: true,
    hoveredPointRingColor: '#edf1f7',
    hoveredLinkColor: '#edf1f7',
    simulationDecay: 7000,
    simulationFriction: 0.72,
    simulationGravity: 0.035,
    simulationRepulsion: 0.72,
    simulationLinkSpring: 0.82,
    simulationLinkDistance: 12,
    enableSimulationDuringZoom: false,
    onZoom: (event, userDriven) => {
      if (!userDriven) return
      scheduleLodForZoom(event?.transform?.k ?? state.graph?.getZoomLevel?.() ?? state.zoomLevel)
    },
    onPointClick: (pointIndex) => {
      const fullPointIndex = state.visibleToFullPointIndex[pointIndex] ?? pointIndex
      const point = state.pointsByIndex[fullPointIndex]
      if (!point) return
      const location = point.file_path ? ` - ${point.file_path}${point.line_start ? `:${point.line_start}` : ''}` : ''
      const typeLabel = edgeStyle(state.pointTypeById.get(point.id)).label
      const degree = state.pointDegrees[fullPointIndex] || 0
      setStatus(`${point.kind}: ${point.label}${location} (${typeLabel}, ${formatNumber(degree)} connection${degree === 1 ? '' : 's'})`, 'ok')
    },
  }
}

function lodLevelForZoom(zoomLevel) {
  if (zoomLevel >= LOD_ZOOM_THRESHOLDS[1]) return 3
  if (zoomLevel >= LOD_ZOOM_THRESHOLDS[0]) return 2
  return 1
}

function lodLabel(level = state.lodLevel) {
  if (level === 3) return 'Detail LOD'
  if (level === 2) return 'Symbol LOD'
  return 'Overview LOD'
}

function syncVisiblePositionsFromGraph() {
  if (!state.graph || !state.visibleToFullPointIndex.length) return
  const positions = state.graph.getPointPositions?.()
  if (!positions || positions.length < state.visibleToFullPointIndex.length * 2) return
  for (let visibleIndex = 0; visibleIndex < state.visibleToFullPointIndex.length; visibleIndex += 1) {
    const fullIndex = state.visibleToFullPointIndex[visibleIndex]
    const sourceOffset = visibleIndex * 2
    const targetOffset = fullIndex * 2
    state.pointPositions[targetOffset] = positions[sourceOffset]
    state.pointPositions[targetOffset + 1] = positions[sourceOffset + 1]
  }
}

function isPrimaryPoint(point) {
  return point?.kind === 'Repository' || point?.kind === 'File'
}

function shouldShowPointAtLod(fullIndex, level) {
  if (level >= 3) return true
  const point = state.pointsByIndex[fullIndex]
  const degree = state.pointDegrees[fullIndex] || 0
  if (isPrimaryPoint(point) || degree >= LOD_HUB_DEGREE_MIN) return true
  if (level >= 2 && point?.kind === 'Symbol') return degree >= LOD_SYMBOL_DEGREE_MIN
  return false
}

function shouldShowLinkAtLod(linkIndex, level) {
  if (level >= 3) return true
  const edgeType = state.linkTypes[linkIndex]
  if (level === 1) return edgeType !== 'USES_VARIABLE' && edgeType !== 'FLOWS_TO'
  return edgeType !== 'USES_VARIABLE'
}

function buildVisibleGraphBuffers() {
  const visiblePointSet = new Set()
  for (let fullIndex = 0; fullIndex < state.pointsByIndex.length; fullIndex += 1) {
    if (shouldShowPointAtLod(fullIndex, state.lodLevel)) visiblePointSet.add(fullIndex)
  }

  if (!visiblePointSet.size && state.pointsByIndex.length) {
    const ranked = state.pointsByIndex
      .map((_, fullIndex) => ({ fullIndex, degree: state.pointDegrees[fullIndex] || 0 }))
      .sort((left, right) => right.degree - left.degree)
      .slice(0, Math.min(300, state.pointsByIndex.length))
    for (const item of ranked) visiblePointSet.add(item.fullIndex)
  }

  const fullToVisiblePointIndex = new Map()
  const pointPositions = []
  const pointColors = []
  const pointSizes = []
  state.visibleToFullPointIndex = []

  for (const fullIndex of visiblePointSet) {
    const visibleIndex = state.visibleToFullPointIndex.length
    fullToVisiblePointIndex.set(fullIndex, visibleIndex)
    state.visibleToFullPointIndex.push(fullIndex)
    const positionOffset = fullIndex * 2
    pointPositions.push(state.pointPositions[positionOffset], state.pointPositions[positionOffset + 1])
    const colorOffset = fullIndex * 4
    pointColors.push(state.pointColors[colorOffset], state.pointColors[colorOffset + 1], state.pointColors[colorOffset + 2], state.pointColors[colorOffset + 3])
    pointSizes.push(state.pointSizes[fullIndex])
  }

  const linkPairs = []
  const linkColors = []
  const linkWidths = []
  if (state.edgesVisible) {
    for (let linkIndex = 0; linkIndex < state.linkTypes.length; linkIndex += 1) {
      if (!shouldShowLinkAtLod(linkIndex, state.lodLevel)) continue
      const pairOffset = linkIndex * 2
      const sourceIndex = fullToVisiblePointIndex.get(state.linkPairs[pairOffset])
      const targetIndex = fullToVisiblePointIndex.get(state.linkPairs[pairOffset + 1])
      if (sourceIndex === undefined || targetIndex === undefined) continue
      linkPairs.push(sourceIndex, targetIndex)
      const colorOffset = linkIndex * 4
      linkColors.push(state.linkColors[colorOffset], state.linkColors[colorOffset + 1], state.linkColors[colorOffset + 2], state.linkColors[colorOffset + 3])
      linkWidths.push(state.linkWidths[linkIndex])
    }
  }

  state.visibleNodes = state.visibleToFullPointIndex.length
  state.visibleEdges = linkWidths.length
  return { pointPositions, pointColors, pointSizes, linkPairs, linkColors, linkWidths }
}

function lodSummary() {
  return `${lodLabel()}: showing ${formatNumber(state.visibleNodes)} of ${formatNumber(state.loadedNodes)} nodes and ${formatNumber(state.visibleEdges)} of ${formatNumber(state.loadedEdges)} edges.`
}

function easeInOutSine(progress) {
  return -(Math.cos(Math.PI * progress) - 1) / 2
}

function visibleTargetPositions() {
  return state.visibleToFullPointIndex.flatMap((fullIndex) => {
    const offset = fullIndex * 2
    return [
      state.pointTargetPositions[offset] ?? state.pointPositions[offset] ?? 0,
      state.pointTargetPositions[offset + 1] ?? state.pointPositions[offset + 1] ?? 0,
    ]
  })
}

function syncFullPositionsFromVisiblePositions(positions) {
  for (let visibleIndex = 0; visibleIndex < state.visibleToFullPointIndex.length; visibleIndex += 1) {
    const fullIndex = state.visibleToFullPointIndex[visibleIndex]
    const sourceOffset = visibleIndex * 2
    const targetOffset = fullIndex * 2
    state.pointPositions[targetOffset] = positions[sourceOffset]
    state.pointPositions[targetOffset + 1] = positions[sourceOffset + 1]
  }
}

function pendingVisiblePoints() {
  const pending = []
  for (let visibleIndex = 0; visibleIndex < state.visibleToFullPointIndex.length; visibleIndex += 1) {
    const fullIndex = state.visibleToFullPointIndex[visibleIndex]
    if (state.pendingRadialPointIndexes.has(fullIndex)) pending.push({ visibleIndex, fullIndex })
  }
  return pending
}

function frameCenterOutView(targetPositions) {
  if (!state.graph || !targetPositions.length) return
  state.graph.fitViewByPointPositions?.(targetPositions, 0, 0.12, false)
}

function startCenterOutLayoutWindow(showStatus = false) {
  if (!state.graph) return
  clearSimulationTimer()
  cancelRadialAnimation()
  state.graph.pause?.()
  state.paused = false
  elements.toggleSim.textContent = 'Pause'

  const pending = pendingVisiblePoints()
  if (!pending.length) {
    startSimulationWindow(showStatus)
    return
  }

  const targetPositions = visibleTargetPositions()
  const originX = 0
  const originY = 0
  frameCenterOutView(targetPositions)

  const currentPositions = state.graph.getPointPositions?.()
  const startPositions = currentPositions && currentPositions.length === targetPositions.length
    ? new Float32Array(currentPositions)
    : new Float32Array(targetPositions)
  for (const { visibleIndex } of pending) {
    const offset = visibleIndex * 2
    startPositions[offset] = originX
    startPositions[offset + 1] = originY
  }
  state.graph.setPointPositions(startPositions)
  state.graph.render()
  if (showStatus) setStatus('Expanding nodes from center for 15 seconds...', 'ok')

  const animatedPositions = new Float32Array(startPositions)
  const startedAt = performance.now()
  const tick = (now) => {
    if (state.paused) return
    const progress = Math.min(1, (now - startedAt) / RADIAL_ANIMATION_MS)
    const easedProgress = easeInOutSine(progress)
    for (const { visibleIndex, fullIndex } of pending) {
      const visibleOffset = visibleIndex * 2
      const fullOffset = fullIndex * 2
      const targetX = state.pointTargetPositions[fullOffset] ?? targetPositions[visibleOffset]
      const targetY = state.pointTargetPositions[fullOffset + 1] ?? targetPositions[visibleOffset + 1]
      animatedPositions[visibleOffset] = originX + (targetX - originX) * easedProgress
      animatedPositions[visibleOffset + 1] = originY + (targetY - originY) * easedProgress
    }
    state.graph.setPointPositions(animatedPositions)
    state.graph.render()

    if (progress < 1) {
      state.radialAnimationFrame = requestAnimationFrame(tick)
      return
    }

    state.radialAnimationFrame = null
    for (const { fullIndex } of pending) state.pendingRadialPointIndexes.delete(fullIndex)
    syncFullPositionsFromVisiblePositions(animatedPositions)
    state.graph.unpause?.()
  }

  state.simulationTimer = setTimeout(() => pauseSimulation(true), SIMULATION_RUN_MS)
  state.radialAnimationFrame = requestAnimationFrame(tick)
}

function applyLodLevel(level, showStatus = false) {
  if (level === state.lodLevel && state.visibleNodes) return
  syncVisiblePositionsFromGraph()
  state.lodLevel = level
  syncGraphBuffers(false)
  startCenterOutLayoutWindow()
  if (showStatus) setStatus(lodSummary(), 'ok')
}

function scheduleLodForZoom(zoomLevel) {
  state.zoomLevel = zoomLevel || 1
  const nextLevel = lodLevelForZoom(state.zoomLevel)
  if (nextLevel === state.lodLevel) return
  if (state.lodFrame) cancelAnimationFrame(state.lodFrame)
  state.lodFrame = requestAnimationFrame(() => {
    state.lodFrame = null
    applyLodLevel(nextLevel, true)
  })
}

function layoutScale() {
  const totalPoints = Math.max(1, state.pointIndexById.size)
  return {
    zoneRadius: Math.min(1450, Math.max(420, Math.sqrt(totalPoints) * 4.2)),
    localStep: totalPoints > 200000 ? 3.8 : totalPoints > 50000 ? 5.2 : 7.8,
  }
}

function preSpreadPosition(pointIndex, ordinal) {
  const point = state.pointsByIndex[pointIndex]
  const edgeType = state.pointTypeById.get(point.id) || 'UNKNOWN'
  const zoneIndex = LAYOUT_ZONE_INDEX.get(edgeType) ?? LAYOUT_ZONE_INDEX.get('UNKNOWN')
  const zoneAngle = -Math.PI / 2 + (Math.PI * 2 * zoneIndex) / LAYOUT_ZONE_ORDER.length
  const { zoneRadius, localStep } = layoutScale()
  const degree = state.pointDegrees[pointIndex] || 0
  const hubPull = Math.min(0.72, Math.log2(degree + 1) / 9)
  const centerDistance = zoneRadius * (1 - hubPull)
  const localAngle = ordinal * GOLDEN_ANGLE + zoneIndex * 0.71
  const localRadius = Math.sqrt(ordinal + 1) * localStep * (1 - hubPull * 0.45)
  return [
    Math.cos(zoneAngle) * centerDistance + Math.cos(localAngle) * localRadius,
    Math.sin(zoneAngle) * centerDistance + Math.sin(localAngle) * localRadius,
  ]
}

function applyPreSpreadLayout(points) {
  for (const point of points) {
    const pointIndex = state.pointIndexById.get(point.id)
    if (pointIndex === undefined) continue
    const edgeType = state.pointTypeById.get(point.id) || 'UNKNOWN'
    const ordinal = state.layoutZoneCounts.get(edgeType) || 0
    state.layoutZoneCounts.set(edgeType, ordinal + 1)
    const [x, y] = preSpreadPosition(pointIndex, ordinal)
    const positionOffset = pointIndex * 2
    state.pointTargetPositions[positionOffset] = x
    state.pointTargetPositions[positionOffset + 1] = y
    state.pointPositions[positionOffset] = 0
    state.pointPositions[positionOffset + 1] = 0
    state.pendingRadialPointIndexes.add(pointIndex)
  }
}

function centerTargetLayout() {
  if (!state.pointTargetPositions.length) return
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (let offset = 0; offset < state.pointTargetPositions.length; offset += 2) {
    const x = state.pointTargetPositions[offset]
    const y = state.pointTargetPositions[offset + 1]
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return
  const centerX = (minX + maxX) / 2
  const centerY = (minY + maxY) / 2
  if (Math.abs(centerX) < 0.001 && Math.abs(centerY) < 0.001) return
  for (let pointIndex = 0; pointIndex < state.pointsByIndex.length; pointIndex += 1) {
    const offset = pointIndex * 2
    state.pointTargetPositions[offset] -= centerX
    state.pointTargetPositions[offset + 1] -= centerY
    if (state.pendingRadialPointIndexes.has(pointIndex)) {
      state.pointPositions[offset] = 0
      state.pointPositions[offset + 1] = 0
    } else {
      state.pointPositions[offset] -= centerX
      state.pointPositions[offset + 1] -= centerY
    }
  }
}

function normalizeBatch(batch) {
  const newPoints = []
  for (const point of batch.points) {
    if (state.pointIndexById.has(point.id)) continue
    const index = state.pointIndexById.size
    state.pointIndexById.set(point.id, index)
    state.pointsByIndex[index] = point
    state.pointPositions.push(0, 0)
    state.pointTargetPositions.push(0, 0)
    pushColor(state.pointColors, edgeColor('UNKNOWN', POINT_ALPHA))
    state.pointDegrees.push(0)
    state.pointSizes.push(pointSizeForDegree(0))
    newPoints.push(point)
  }

  const newLinks = []
  for (const link of batch.links) {
    if (state.loadedLinkIds.has(link.id)) continue
    const sourceIndex = state.pointIndexById.get(link.source)
    const targetIndex = state.pointIndexById.get(link.target)
    if (sourceIndex === undefined || targetIndex === undefined) continue
    state.loadedLinkIds.add(link.id)
    state.linkPairs.push(sourceIndex, targetIndex)
    pushColor(state.linkColors, edgeColor(link.type, LINK_ALPHA))
    state.linkTypes.push(link.type)
    state.linkWidths.push(edgeStyle(link.type).width)
    incrementPointDegree(sourceIndex)
    incrementPointDegree(targetIndex)
    assignPointType(link.source, link.type)
    assignPointType(link.target, link.type)
    newLinks.push(link)
  }
  applyPreSpreadLayout(newPoints)
  centerTargetLayout()
  return { points: newPoints, links: newLinks }
}

function syncGraphBuffers(syncExistingPositions = true) {
  if (syncExistingPositions) syncVisiblePositionsFromGraph()
  if (!state.graph) {
    state.graph = new Graph(elements.graphRoot, graphConfig())
  }
  const visible = buildVisibleGraphBuffers()
  state.graph.setPointPositions(new Float32Array(visible.pointPositions))
  state.graph.setPointColors(new Float32Array(visible.pointColors))
  state.graph.setPointSizes(new Float32Array(visible.pointSizes))
  state.graph.setLinks(new Float32Array(visible.linkPairs))
  state.graph.setLinkColors(new Float32Array(visible.linkColors))
  state.graph.setLinkWidths(new Float32Array(visible.linkWidths))
  state.graph.render()
}

async function appendBatch(batch, reset) {
  if (state.graph) syncVisiblePositionsFromGraph()
  const normalized = normalizeBatch(batch)
  if (!state.graph || reset) {
    await destroyGraph()
  }
  syncGraphBuffers(false)
  startCenterOutLayoutWindow()

  state.loadedNodes += normalized.points.length
  state.loadedEdges += normalized.links.length
  state.hasNext = batch.next_offset !== null
  state.nextOffset = batch.next_offset ?? (batch.offset + batch.links.length)
  elements.loadNext.disabled = !state.hasNext
  updateCounters()
}

async function loadStats(projectName) {
  const stats = await api(`/api/viewer/graphs/${encodeURIComponent(projectName)}/stats`)
  elements.dbNodes.textContent = formatNumber(stats.total_nodes)
  elements.dbEdges.textContent = formatNumber(stats.total_edges)
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
  setStatus(`Loading ${formatNumber(chunkLimit())} edges from ${projectName}...`)
  try {
    if (reset) {
      await destroyGraph()
      resetState()
      await loadStats(projectName)
    }
    const batch = await api(`/api/viewer/graphs/${encodeURIComponent(projectName)}/chunk?${params}`)
    await appendBatch(batch, reset)
    const more = batch.next_offset === null ? 'No more chunks for this filter.' : 'Ready for the next chunk.'
    setStatus(`Loaded ${formatNumber(batch.points.length)} nodes and ${formatNumber(batch.links.length)} edges. ${lodSummary()} ${more}`, 'ok')
  } catch (error) {
    setStatus(error.message, 'error')
  } finally {
    elements.loadFirst.disabled = false
    if (state.hasNext && state.graph) elements.loadNext.disabled = false
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
  elements.fitView.addEventListener('click', () => state.graph?.fitView?.(350, 0.12))
  elements.toggleEdges.addEventListener('click', () => setEdgesVisible(!state.edgesVisible, true))
  elements.toggleSim.addEventListener('click', () => {
    if (!state.graph) return
    if (state.paused) startCenterOutLayoutWindow(true)
    else pauseSimulation()
  })
  elements.projectSelect.addEventListener('change', async () => {
    if (elements.projectSelect.value) await loadStats(elements.projectSelect.value)
  })
  elements.saveToken.addEventListener('click', () => {
    const value = elements.tokenInput.value.trim()
    if (value) {
      localStorage.setItem('cg_jwt', value)
      elements.tokenInput.value = ''
      elements.tokenInput.placeholder = 'Using saved session token'
    }
    setStatus('Session token saved.', 'ok')
  })
  elements.forgetToken.addEventListener('click', () => {
    localStorage.removeItem('cg_jwt')
    elements.tokenInput.value = ''
    elements.tokenInput.placeholder = 'Uses cg_jwt from Admin'
    setStatus('Session token removed.', 'ok')
  })
}

async function boot() {
  if (token()) elements.tokenInput.placeholder = 'Using saved session token'
  setControlPanelCollapsed(localStorage.getItem('cg_viewer_controls_collapsed') === '1')
  setEdgesVisible(localStorage.getItem('cg_viewer_edges_visible') !== '0')
  wireEvents()
  await loadProjects()
}

boot().catch((error) => setStatus(error.message, 'error'))
