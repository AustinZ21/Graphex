const KIND_ORDER = ['Repository', 'File', 'Symbol', 'Variable', 'Node']
const KIND_INDEX = new Map(KIND_ORDER.map((kind, index) => [kind, index]))
const GOLDEN_ANGLE = 2.399963229728653
const BASE_DEPTH = 900
const LAYOUT_RELAX_ITERATIONS = 3
const LAYOUT_RELAX_MAX_POINTS = 10000
const LAYOUT_BARNES_HUT_THETA = 0.72
const LAYOUT_REPULSION = 1500
const LAYOUT_LINK_DISTANCE = 210
const LAYOUT_LINK_STRENGTH = 0.035
const LAYOUT_COLLISION_PADDING = 22
const LAYOUT_COLLISION_CELL_SIZE = 260
const LAYOUT_MAX_STEP = 95
const LAYOUT_MAX_DEPTH = 16
const LAYOUT_SETTING_SCHEMA = Object.freeze({
  relaxIterations: { defaultValue: LAYOUT_RELAX_ITERATIONS, min: 0, max: 12, integer: true },
  relaxMaxPoints: { defaultValue: LAYOUT_RELAX_MAX_POINTS, min: 0, max: 50000, integer: true },
  barnesHutTheta: { defaultValue: LAYOUT_BARNES_HUT_THETA, min: 0.3, max: 1.5 },
  repulsion: { defaultValue: LAYOUT_REPULSION, min: 0, max: 6000 },
  linkDistance: { defaultValue: LAYOUT_LINK_DISTANCE, min: 20, max: 800 },
  linkStrength: { defaultValue: LAYOUT_LINK_STRENGTH, min: 0, max: 0.2 },
  collisionPadding: { defaultValue: LAYOUT_COLLISION_PADDING, min: 0, max: 120 },
  collisionCellSize: { defaultValue: LAYOUT_COLLISION_CELL_SIZE, min: 80, max: 800 },
  maxStep: { defaultValue: LAYOUT_MAX_STEP, min: 5, max: 300 },
  maxDepth: { defaultValue: LAYOUT_MAX_DEPTH, min: 8, max: 24, integer: true },
})

function clamp(value, minValue, maxValue) {
  return Math.max(minValue, Math.min(maxValue, value))
}

function normalizeLayoutSetting(key, value) {
  const schema = LAYOUT_SETTING_SCHEMA[key]
  if (!schema) return undefined
  const numericValue = Number(value)
  const fallbackValue = schema.defaultValue
  const boundedValue = Number.isFinite(numericValue) ? clamp(numericValue, schema.min, schema.max) : fallbackValue
  return schema.integer ? Math.round(boundedValue) : Number(boundedValue.toFixed(4))
}

function normalizeLayoutSettings(settings = {}) {
  const normalized = {}
  for (const key of Object.keys(LAYOUT_SETTING_SCHEMA)) {
    normalized[key] = normalizeLayoutSetting(key, settings[key])
  }
  return normalized
}

function hashString(value) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function normalizeNodeKind(kind) {
  return KIND_INDEX.has(kind) ? kind : 'Node'
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

function layoutMass(degree) {
  return 1 + Math.log2(degree + 1) * 1.7
}

function layoutCollisionRadius(degree, settings) {
  return 18 + Math.log2(degree + 1) * 8 + settings.collisionPadding
}

function safeLayoutVector(deltaX, deltaY, fallbackIndex) {
  const distance = Math.hypot(deltaX, deltaY)
  if (distance > 0.0001) return { x: deltaX / distance, y: deltaY / distance, distance }
  const angle = fallbackIndex * GOLDEN_ANGLE
  return { x: Math.cos(angle), y: Math.sin(angle), distance: 0.0001 }
}

function buildLayoutModel(points, links, settings) {
  const indexById = new Map()
  points.forEach((point, index) => indexById.set(point.id, index))

  const degrees = new Float32Array(points.length)
  const edgeSources = []
  const edgeTargets = []

  for (const link of links || []) {
    const sourceIndex = indexById.get(link.source)
    const targetIndex = indexById.get(link.target)
    if (sourceIndex === undefined || targetIndex === undefined) continue
    degrees[sourceIndex] += 1
    degrees[targetIndex] += 1
    if (sourceIndex === targetIndex) continue
    edgeSources.push(sourceIndex)
    edgeTargets.push(targetIndex)
  }

  const masses = new Float32Array(points.length)
  const radii = new Float32Array(points.length)
  for (let index = 0; index < points.length; index += 1) {
    masses[index] = layoutMass(degrees[index])
    radii[index] = layoutCollisionRadius(degrees[index], settings)
  }

  return { degrees, masses, radii, edgeSources, edgeTargets }
}

function createQuadNode(minX, minY, maxX, maxY) {
  return { minX, minY, maxX, maxY, mass: 0, centerX: 0, centerY: 0, point: -1, children: null }
}

function subdivideQuad(node) {
  const midX = (node.minX + node.maxX) / 2
  const midY = (node.minY + node.maxY) / 2
  node.children = [
    createQuadNode(node.minX, node.minY, midX, midY),
    createQuadNode(midX, node.minY, node.maxX, midY),
    createQuadNode(node.minX, midY, midX, node.maxY),
    createQuadNode(midX, midY, node.maxX, node.maxY),
  ]
}

function quadChildFor(node, x, y) {
  const midX = (node.minX + node.maxX) / 2
  const midY = (node.minY + node.maxY) / 2
  return (y >= midY ? 2 : 0) + (x >= midX ? 1 : 0)
}

function insertQuadPoint(node, pointIndex, positionsX, positionsY, masses, settings, depth = 0) {
  const x = positionsX[pointIndex]
  const y = positionsY[pointIndex]
  const mass = masses[pointIndex]
  const nextMass = node.mass + mass
  node.centerX = nextMass ? ((node.centerX * node.mass) + (x * mass)) / nextMass : x
  node.centerY = nextMass ? ((node.centerY * node.mass) + (y * mass)) / nextMass : y
  node.mass = nextMass

  if (!node.children && node.point === -1) {
    node.point = pointIndex
    return
  }
  if (!node.children) {
    if (depth >= settings.maxDepth) return
    const existingPoint = node.point
    node.point = -1
    subdivideQuad(node)
    insertQuadPoint(node.children[quadChildFor(node, positionsX[existingPoint], positionsY[existingPoint])], existingPoint, positionsX, positionsY, masses, settings, depth + 1)
  }
  insertQuadPoint(node.children[quadChildFor(node, x, y)], pointIndex, positionsX, positionsY, masses, settings, depth + 1)
}

function buildBarnesHutTree(positionsX, positionsY, masses, count, settings) {
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (let index = 0; index < count; index += 1) {
    minX = Math.min(minX, positionsX[index])
    minY = Math.min(minY, positionsY[index])
    maxX = Math.max(maxX, positionsX[index])
    maxY = Math.max(maxY, positionsY[index])
  }
  const span = Math.max(maxX - minX, maxY - minY, 1)
  const padding = span * 0.05 + 1
  const root = createQuadNode(minX - padding, minY - padding, maxX + padding, maxY + padding)
  for (let index = 0; index < count; index += 1) insertQuadPoint(root, index, positionsX, positionsY, masses, settings)
  return root
}

function applyBarnesHutRepulsion(node, pointIndex, positionsX, positionsY, masses, deltasX, deltasY, settings) {
  if (!node.mass || (node.point === pointIndex && !node.children)) return
  const deltaX = positionsX[pointIndex] - node.centerX
  const deltaY = positionsY[pointIndex] - node.centerY
  const vector = safeLayoutVector(deltaX, deltaY, pointIndex)
  const width = node.maxX - node.minX

  if (!node.children || width / Math.max(vector.distance, 1) < settings.barnesHutTheta) {
    const distanceSq = Math.max(vector.distance * vector.distance, 64)
    const force = (settings.repulsion * masses[pointIndex] * node.mass) / distanceSq
    deltasX[pointIndex] += vector.x * force
    deltasY[pointIndex] += vector.y * force
    return
  }

  for (const child of node.children) applyBarnesHutRepulsion(child, pointIndex, positionsX, positionsY, masses, deltasX, deltasY, settings)
}

function applyLinkAttraction(model, positionsX, positionsY, deltasX, deltasY, settings) {
  for (let edgeIndex = 0; edgeIndex < model.edgeSources.length; edgeIndex += 1) {
    const sourceIndex = model.edgeSources[edgeIndex]
    const targetIndex = model.edgeTargets[edgeIndex]
    const deltaX = positionsX[targetIndex] - positionsX[sourceIndex]
    const deltaY = positionsY[targetIndex] - positionsY[sourceIndex]
    const vector = safeLayoutVector(deltaX, deltaY, sourceIndex + targetIndex)
    const minDegree = Math.max(1, Math.min(model.degrees[sourceIndex], model.degrees[targetIndex]))
    const targetDistance = settings.linkDistance + Math.log2(minDegree + 1) * 18
    const linkStrength = settings.linkStrength / minDegree
    const pull = (vector.distance - targetDistance) * linkStrength
    const sourceMass = model.masses[sourceIndex]
    const targetMass = model.masses[targetIndex]
    const totalMass = sourceMass + targetMass
    const sourceShare = targetMass / totalMass
    const targetShare = sourceMass / totalMass
    deltasX[sourceIndex] += vector.x * pull * sourceShare
    deltasY[sourceIndex] += vector.y * pull * sourceShare
    deltasX[targetIndex] -= vector.x * pull * targetShare
    deltasY[targetIndex] -= vector.y * pull * targetShare
  }
}

function collisionCellKey(cellX, cellY) {
  return `${cellX}:${cellY}`
}

function applyCollisionForce(model, positionsX, positionsY, deltasX, deltasY, settings) {
  const cells = new Map()
  for (let index = 0; index < positionsX.length; index += 1) {
    const cellX = Math.floor(positionsX[index] / settings.collisionCellSize)
    const cellY = Math.floor(positionsY[index] / settings.collisionCellSize)
    const key = collisionCellKey(cellX, cellY)
    let bucket = cells.get(key)
    if (!bucket) {
      bucket = []
      cells.set(key, bucket)
    }
    bucket.push(index)
  }

  for (let index = 0; index < positionsX.length; index += 1) {
    const cellX = Math.floor(positionsX[index] / settings.collisionCellSize)
    const cellY = Math.floor(positionsY[index] / settings.collisionCellSize)
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        const bucket = cells.get(collisionCellKey(cellX + offsetX, cellY + offsetY))
        if (!bucket) continue
        for (const otherIndex of bucket) {
          if (otherIndex <= index) continue
          const requiredDistance = model.radii[index] + model.radii[otherIndex]
          const deltaX = positionsX[index] - positionsX[otherIndex]
          const deltaY = positionsY[index] - positionsY[otherIndex]
          const distance = Math.hypot(deltaX, deltaY)
          if (distance >= requiredDistance) continue
          const vector = safeLayoutVector(deltaX, deltaY, index + otherIndex)
          const push = (requiredDistance - distance) * 0.58
          deltasX[index] += vector.x * push
          deltasY[index] += vector.y * push
          deltasX[otherIndex] -= vector.x * push
          deltasY[otherIndex] -= vector.y * push
        }
      }
    }
  }
}

function relaxLayoutPositions(points, links, baseNodeIndex, layoutSettings) {
  const settings = normalizeLayoutSettings(layoutSettings)
  const positions = new Float32Array(points.length * 3)
  for (let index = 0; index < points.length; index += 1) {
    const position = initial3dPosition(points[index], baseNodeIndex + index)
    const offset = index * 3
    positions[offset] = position.x3d
    positions[offset + 1] = position.y3d
    positions[offset + 2] = position.z3d
  }

  if (points.length < 2 || points.length > settings.relaxMaxPoints) return positions

  const model = buildLayoutModel(points, links, settings)
  const positionsX = new Float32Array(points.length)
  const positionsY = new Float32Array(points.length)
  const deltasX = new Float32Array(points.length)
  const deltasY = new Float32Array(points.length)
  for (let index = 0; index < points.length; index += 1) {
    const offset = index * 3
    positionsX[index] = positions[offset]
    positionsY[index] = positions[offset + 1]
  }

  for (let iteration = 0; iteration < settings.relaxIterations; iteration += 1) {
    deltasX.fill(0)
    deltasY.fill(0)
    const root = buildBarnesHutTree(positionsX, positionsY, model.masses, points.length, settings)
    for (let index = 0; index < points.length; index += 1) {
      applyBarnesHutRepulsion(root, index, positionsX, positionsY, model.masses, deltasX, deltasY, settings)
    }
    applyLinkAttraction(model, positionsX, positionsY, deltasX, deltasY, settings)
    applyCollisionForce(model, positionsX, positionsY, deltasX, deltasY, settings)

    for (let index = 0; index < points.length; index += 1) {
      const step = Math.hypot(deltasX[index], deltasY[index])
      const scale = step > settings.maxStep ? settings.maxStep / step : 1
      positionsX[index] += deltasX[index] * scale
      positionsY[index] += deltasY[index] * scale
    }
  }

  for (let index = 0; index < points.length; index += 1) {
    const offset = index * 3
    positions[offset] = positionsX[index]
    positions[offset + 1] = positionsY[index]
  }
  return positions
}

self.addEventListener('message', (event) => {
  const message = event.data || {}
  if (message.type !== 'preprocessBatch') return

  const points = Array.isArray(message.points) ? message.points : []
  const links = Array.isArray(message.links) ? message.links : []
  const baseNodeIndex = Number(message.baseNodeIndex || 0)
  const positions = relaxLayoutPositions(points, links, baseNodeIndex, message.layoutSettings)

  self.postMessage(
    { id: message.id, type: 'preprocessBatchDone', positions: positions.buffer },
    [positions.buffer],
  )
})
