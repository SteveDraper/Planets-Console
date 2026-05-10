import '@testing-library/jest-dom/vitest'

type StorageData = Record<string, string>

function createMemoryStorage(): Storage {
  let data: StorageData = {}
  return {
    get length() {
      return Object.keys(data).length
    },
    clear() {
      data = {}
    },
    getItem(key: string) {
      return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null
    },
    key(index: number) {
      return Object.keys(data)[index] ?? null
    },
    removeItem(key: string) {
      delete data[key]
    },
    setItem(key: string, value: string) {
      data[key] = String(value)
    },
  }
}

function installStorageGlobal(name: 'localStorage' | 'sessionStorage') {
  const existing = globalThis[name] ?? window[name]
  Object.defineProperty(globalThis, name, {
    configurable: true,
    value: existing ?? createMemoryStorage(),
  })
}

installStorageGlobal('localStorage')
installStorageGlobal('sessionStorage')
