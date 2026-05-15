const KIND_ORDER = ['Repository', 'File', 'Symbol', 'Variable', 'Node']
const KIND_INDEX = new Map(KIND_ORDER.map((kind, index) => [kind, index]))
const GOLDEN_ANGLE = 2.399963229728653
const BASE_DEPTH = 900

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

self.addEventListener('message', (event) => {
  const message = event.data || {}
  if (message.type !== 'preprocessBatch') return

  const points = Array.isArray(message.points) ? message.points : []
  const baseNodeIndex = Number(message.baseNodeIndex || 0)
  const positions = new Float32Array(points.length * 3)

  for (let index = 0; index < points.length; index += 1) {
    const position = initial3dPosition(points[index], baseNodeIndex + index)
    const offset = index * 3
    positions[offset] = position.x3d
    positions[offset + 1] = position.y3d
    positions[offset + 2] = position.z3d
  }

  self.postMessage(
    { id: message.id, type: 'preprocessBatchDone', positions: positions.buffer },
    [positions.buffer],
  )
})
