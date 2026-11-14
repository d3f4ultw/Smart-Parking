import assert from 'node:assert/strict'
import { setTimeout as pause } from 'node:timers/promises'

export class FuenteEventosSimulada {
  listeners = new Map()
  closed = false

  constructor(url) {
    this.url = url
  }

  addEventListener(tipo, listener) {
    const listeners = this.listeners.get(tipo) ?? []
    listeners.push(listener)
    this.listeners.set(tipo, listeners)
  }

  emitir(tipo, evento) {
    for (const listener of this.listeners.get(tipo) ?? []) listener(evento)
  }

  close() {
    this.closed = true
  }
}

export async function esperar(condicion, mensaje, limiteMs = 2_000) {
  for (let transcurrido = 0; transcurrido < limiteMs; transcurrido += 25) {
    if (condicion()) return
    await pause(25)
  }
  assert.fail(mensaje)
}
