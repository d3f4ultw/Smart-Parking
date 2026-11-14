const destinos = {
  api: 'http://api:8080/actuator/health',
  web: 'http://web:3000/panel',
}
const nombre = process.argv[2]
if (!(nombre in destinos)) throw new Error('Servicio de espera desconocido.')
const inicio = Date.now()
for (let intento = 1; intento <= 120; intento += 1) {
  try {
    const respuesta = await fetch(destinos[nombre], { signal: AbortSignal.timeout(2_000) })
    if (respuesta.status === 200) {
      console.log(`${nombre}: HTTP 200; intentos=${intento}; tiempoMs=${Date.now() - inicio}`)
      process.exit(0)
    }
  } catch {
    // Reintento acotado dentro de la red QA aislada.
  }
  await new Promise((resolver) => setTimeout(resolver, 1_000))
}
console.error(`${nombre}: no listo tras 120 intentos.`)
process.exit(5)
