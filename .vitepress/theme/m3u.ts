export interface M3uEntry {
  name: string
  group: string
  logo: string
  url: string
}

export function getM3uAttr(line: string, name: string) {
  const match = line.match(new RegExp(`${name}="([^"]*)"`))
  return match ? match[1] : ''
}

export function parseM3u(text: string) {
  const entries: M3uEntry[] = []
  let current: Omit<M3uEntry, 'url'> | null = null

  for (const sourceLine of text.split(/\r?\n/)) {
    const line = sourceLine.trim()
    if (!line) continue

    if (line.startsWith('#EXTINF')) {
      const commaIndex = line.lastIndexOf(',')
      const name = commaIndex >= 0 ? line.slice(commaIndex + 1).trim() : getM3uAttr(line, 'tvg-name')

      current = {
        name: name || '未命名频道',
        group: getM3uAttr(line, 'group-title') || '未分组',
        logo: getM3uAttr(line, 'tvg-logo')
      }
      continue
    }

    if (current && /^https?:\/\//.test(line)) {
      entries.push({ ...current, url: line })
      current = null
    }
  }

  return entries
}

export async function fetchM3u(basePath: string) {
  const response = await fetch(`${basePath}index.m3u`, { cache: 'no-store' })

  if (!response.ok) {
    throw new Error(`订阅文件读取失败：${response.status}`)
  }

  return response.text()
}
