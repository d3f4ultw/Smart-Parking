import assert from 'node:assert/strict'
import { readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const dependenciasPnpm = await readdir(new URL('../node_modules/.pnpm/', import.meta.url))
const paqueteVue = dependenciasPnpm.find((nombre) => nombre.startsWith('vue@'))
assert.ok(paqueteVue, 'Vue debe estar disponible como dependencia transitiva de Nuxt.')
const vue = require(
  fileURLToPath(new URL(`../node_modules/.pnpm/${paqueteVue}/node_modules/vue`, import.meta.url)),
)
export const { computed, reactive, ref, watch } = vue
export const delay = (milisegundos) => new Promise((resolve) => setTimeout(resolve, milisegundos))

export function evaluarTypescript(origen, dependencias, globales = {}) {
  const javascript = ts.transpileModule(origen, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const modulo = { exports: {} }
  const cargar = (nombre) => {
    if (Object.hasOwn(dependencias, nombre)) return dependencias[nombre]
    return require(nombre)
  }
  const nombres = Object.keys(globales)
  const valores = Object.values(globales)
  new Function('require', 'module', 'exports', ...nombres, javascript)(
    cargar,
    modulo,
    modulo.exports,
    ...valores,
  )
  return modulo.exports
}
