<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  formatearDuracion,
  formatearFecha,
  segundosRestantes,
  type EstadoInscripcionGestion,
} from '~/utils/gestion-propietario'

const props = defineProps<{
  inscripciones: EstadoInscripcionGestion[]
  consultadoEn: number
  ownerActivo: boolean
  ownerCorreo: string | null
  permitirReenvio: boolean
  reenviandoId: number | null
}>()

const emit = defineEmits<{ reenviar: [id: number] }>()
const ahora = ref(0)
const filasSkeleton = [3, 3, 2]
let temporizador: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  ahora.value = Date.now()
  temporizador = setInterval(() => {
    ahora.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (temporizador !== undefined) {
    clearInterval(temporizador)
  }
})

const ordenadas = computed(() => [...props.inscripciones].sort((a, b) =>
  Date.parse(a.proceso_expira_en) - Date.parse(b.proceso_expira_en)))

function tiempoProceso(inscripcion: EstadoInscripcionGestion) {
  return segundosRestantes(inscripcion.segundos_proceso, props.consultadoEn, ahora.value)
}

function tiempoCooldown(inscripcion: EstadoInscripcionGestion) {
  return segundosRestantes(inscripcion.segundos_cooldown, props.consultadoEn, ahora.value)
}

function etiquetaEstado(inscripcion: EstadoInscripcionGestion) {
  if (inscripcion.estado !== 'completado') {
    return inscripcion.estado
  }
  return inscripcionVinculada(inscripcion) ? 'Vinculado' : 'Desvinculado'
}

function claseEstado(inscripcion: EstadoInscripcionGestion) {
  if (inscripcion.estado !== 'completado') {
    return `status-${inscripcion.estado}`
  }
  return inscripcionVinculada(inscripcion)
    ? 'status-completado'
    : 'status-desvinculado'
}

function inscripcionVinculada(inscripcion: EstadoInscripcionGestion) {
  return inscripcion.estado === 'completado'
    && props.ownerActivo
    && props.ownerCorreo?.trim().toLowerCase() === inscripcion.correo.trim().toLowerCase()
}

function enlaceSigueVigente(inscripcion: EstadoInscripcionGestion) {
  return inscripcion.enlace_vigente
    && Date.parse(inscripcion.expira_en) > ahora.value
    && tiempoProceso(inscripcion) > 0
}

function puedeReenviar(inscripcion: EstadoInscripcionGestion) {
  return props.permitirReenvio
    && !props.ownerActivo
    && inscripcion.estado === 'pendiente'
    && tiempoCooldown(inscripcion) === 0
    && tiempoProceso(inscripcion) > 0
}

function mostrarCooldownEnBoton(inscripcion: EstadoInscripcionGestion) {
  return props.permitirReenvio
    && !props.ownerActivo
    && inscripcion.estado === 'pendiente'
    && tiempoCooldown(inscripcion) > 0
    && tiempoProceso(inscripcion) > 0
}

function textoBotonReenvio(inscripcion: EstadoInscripcionGestion) {
  if (props.reenviandoId === inscripcion.id) {
    return 'Enviando…'
  }
  if (mostrarCooldownEnBoton(inscripcion)) {
    return `Reenviar en ${formatearDuracion(tiempoCooldown(inscripcion))}`
  }
  return 'Reenviar verificación'
}

function motivoReenvio(inscripcion: EstadoInscripcionGestion) {
  if (props.ownerActivo) {
    return 'Ya existe un dueño activo.'
  }
  if (tiempoProceso(inscripcion) === 0) {
    return 'El proceso de 60 minutos terminó.'
  }
  if (inscripcion.estado !== 'pendiente') {
    return inscripcion.motivo_bloqueo ?? 'El proceso no admite reenvíos.'
  }
  if (tiempoCooldown(inscripcion) > 0) {
    return `Disponible en ${formatearDuracion(tiempoCooldown(inscripcion))}.`
  }
  return inscripcion.motivo_bloqueo ?? 'El reenvío no está disponible.'
}

function proximoReenvio(inscripcion: EstadoInscripcionGestion) {
  return puedeReenviar(inscripcion)
    ? 'Disponible ahora'
    : formatearFecha(inscripcion.proximo_reenvio_en)
}
</script>

<template>
  <section class="enrollment-list" aria-labelledby="enrollment-list-title">
    <div class="section-heading">
      <div>
        <h2 id="enrollment-list-title">Procesos de registro</h2>
      </div>
      <span class="record-count">{{ inscripciones.length }} registro(s)</span>
    </div>

    <p v-if="inscripciones.length === 0" class="empty-state">
      No hay procesos de registro de dueño.
    </p>

    <article
      v-for="inscripcion in ordenadas"
      :key="inscripcion.id"
      class="enrollment-card"
      :aria-busy="reenviandoId === inscripcion.id"
    >
      <header class="enrollment-heading">
        <div>
          <h3>{{ inscripcion.correo }}</h3>
          <span class="status-chip" :class="claseEstado(inscripcion)">
            {{ etiquetaEstado(inscripcion) }}
          </span>
        </div>
      </header>

      <div
        v-if="reenviandoId === inscripcion.id"
        class="enrollment-details enrollment-details-skeleton"
        role="status"
        aria-label="Actualizando el estado del correo"
      >
        <div
          v-for="(cantidadFilas, grupo) in filasSkeleton"
          :key="grupo"
          class="detail-group detail-group-skeleton"
          aria-hidden="true"
        >
          <span class="skeleton-line skeleton-title" />
          <div class="skeleton-list">
            <div v-for="fila in cantidadFilas" :key="fila" class="skeleton-row">
              <span class="skeleton-line skeleton-label" />
              <span class="skeleton-line skeleton-value" />
            </div>
          </div>
        </div>
      </div>
      <p
        v-else-if="inscripcion.estado === 'completado'"
        class="linked-state"
        :class="{ 'unlinked-state': !inscripcionVinculada(inscripcion) }"
        role="status"
      >
        {{ inscripcionVinculada(inscripcion)
          ? 'El dueño está vinculado actualmente.'
          : 'El dueño fue desvinculado.' }}
      </p>
      <div v-else class="enrollment-details">
        <section class="detail-group" aria-label="Verificación">
          <h4>Verificación</h4>
          <dl class="detail-list">
            <div>
              <dt>Correo enviado</dt>
              <dd>{{ inscripcion.correo_inicial_enviado ? 'Sí' : 'No' }}</dd>
            </div>
            <div>
              <dt>Estado del enlace</dt>
              <dd>{{ enlaceSigueVigente(inscripcion) ? 'Vigente' : 'No vigente' }}</dd>
            </div>
            <div>
              <dt>Vigente hasta</dt>
              <dd>{{ formatearFecha(inscripcion.expira_en) }}</dd>
            </div>
          </dl>
        </section>

        <section class="detail-group" aria-label="Reenvíos">
          <h4>Reenvíos</h4>
          <dl class="detail-list">
            <div>
              <dt>Intentos usados</dt>
              <dd>
                {{ inscripcion.reenviados_usados }} de
                {{ inscripcion.reenviados_usados + inscripcion.reenviados_restantes }}
              </dd>
            </div>
            <div>
              <dt>Tiempo de espera</dt>
              <dd>{{ formatearDuracion(tiempoCooldown(inscripcion)) }}</dd>
            </div>
            <div>
              <dt>Próximo reenvío</dt>
              <dd>{{ proximoReenvio(inscripcion) }}</dd>
            </div>
          </dl>
        </section>

        <section class="detail-group" aria-label="Correo reservado">
          <h4>Correo reservado</h4>
          <dl class="detail-list">
            <div>
              <dt>Podrás cambiarlo en</dt>
              <dd>{{ formatearDuracion(tiempoProceso(inscripcion)) }}</dd>
            </div>
            <div>
              <dt>Podrás cambiarlo a partir de</dt>
              <dd>{{ formatearFecha(inscripcion.proceso_expira_en) }}</dd>
            </div>
          </dl>
        </section>
      </div>

      <p
        v-if="inscripcion.estado !== 'completado' && !puedeReenviar(inscripcion) && !mostrarCooldownEnBoton(inscripcion)"
        class="blocked-reason"
      >
        {{ motivoReenvio(inscripcion) }}
      </p>
      <button
        v-if="permitirReenvio && inscripcion.estado !== 'completado'"
        class="secondary-button"
        type="button"
        :disabled="!puedeReenviar(inscripcion) || reenviandoId === inscripcion.id"
        @click="emit('reenviar', inscripcion.id)"
      >
        {{ textoBotonReenvio(inscripcion) }}
      </button>
    </article>
  </section>
</template>

<style scoped>
.enrollment-list {
  display: grid;
  gap: 1.25rem;
}

.section-heading,
.enrollment-heading,
.enrollment-heading > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.section-heading h2,
.enrollment-heading h3 {
  margin: 0;
  color: #30263b;
}

.section-heading h2 {
  font-size: 1.15rem;
}

.enrollment-heading h3 {
  overflow-wrap: anywhere;
  font-size: 1rem;
}

.eyebrow {
  margin: 0 0 0.25rem;
  color: #74647f;
  font-size: 0.69rem;
  font-weight: 750;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

.record-count {
  color: #6e6675;
  font-size: 0.82rem;
}

.empty-state,
.enrollment-card {
  margin: 0;
  padding: 1.25rem;
  background: #ffffff;
  border: 1px solid #e5e0e9;
  border-radius: 0.85rem;
}

.enrollment-card {
  display: grid;
  gap: 1.25rem;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.55rem;
  color: #544269;
  background: #eee8f4;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
}

.status-expirado,
.status-bloqueado {
  color: #843f38;
  background: #f9e9e5;
}

.status-completado {
  color: #286348;
  background: #e3f2e8;
}

.status-desvinculado {
  color: #62556f;
  background: #efedf2;
}

.enrollment-details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: start;
  gap: 0.75rem;
  margin: 0;
}

.detail-group-skeleton {
  display: grid;
  gap: 0.75rem;
}

.skeleton-list {
  display: grid;
  gap: 0.75rem;
}

.skeleton-row {
  display: grid;
  gap: 0.2rem;
}

.skeleton-line {
  display: block;
  background: linear-gradient(100deg, #f0edf3 20%, #f9f8fa 42%, #f0edf3 64%);
  background-size: 220% 100%;
  border-radius: 0.3rem;
  animation: enrollment-skeleton 1.4s ease-in-out infinite;
}

.skeleton-title {
  width: 42%;
  height: 0.8rem;
  margin-bottom: 0.05rem;
}

.skeleton-label {
  width: 48%;
  height: 0.76rem;
}

.skeleton-value {
  width: 68%;
  height: 0.88rem;
  margin-top: 0.2rem;
}

.detail-group {
  min-width: 0;
  padding: 0.9rem;
  background: #faf8fc;
  border: 1px solid #ebe5ef;
  border-radius: 0.7rem;
}

.detail-group h4 {
  margin: 0 0 0.75rem;
  color: #443653;
  font-size: 0.8rem;
  font-weight: 750;
}

.detail-list {
  display: grid;
  gap: 0.75rem;
  margin: 0;
}

.detail-list div {
  min-width: 0;
}

.detail-list dt {
  color: #756c7d;
  font-size: 0.76rem;
}

.detail-list dd {
  margin: 0.2rem 0 0;
  color: #332a3e;
  font-size: 0.88rem;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.blocked-reason {
  margin: 0;
  color: #744943;
  font-size: 0.84rem;
}

.linked-state {
  margin: 0;
  color: #286348;
  font-size: 0.9rem;
  font-weight: 650;
}

.unlinked-state {
  color: #62556f;
}

.secondary-button {
  justify-self: start;
  min-width: 11.5rem;
  min-height: 2.6rem;
  padding: 0.6rem 0.9rem;
  color: #51356e;
  background: #ffffff;
  border: 1px solid #9b83b0;
  border-radius: 0.65rem;
  font: inherit;
  font-size: 0.86rem;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
}

.secondary-button:disabled {
  color: #817987;
  background: #f2f0f4;
  border-color: #dcd7e0;
  cursor: not-allowed;
}

@keyframes enrollment-skeleton {
  to {
    background-position: -220% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-line {
    animation: none;
  }
}

@media (max-width: 58rem) {
  .enrollment-details {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 40rem) {
  .enrollment-details {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
