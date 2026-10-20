<script setup lang="ts">
definePageMeta({ layout: false })

useHead({
  title: 'Resultado del pago | Smart Parking',
  meta: [
    { name: 'description', content: 'Consulta el estado de tu membresía desde tu cuenta de cliente.' },
    { name: 'robots', content: 'noindex, nofollow, noarchive' },
    { name: 'referrer', content: 'no-referrer' },
  ],
})
</script>

<template>
  <main class="result-shell" aria-labelledby="result-title">
    <section class="result-card">
      <span class="result-mark" aria-hidden="true">i</span>
      <p class="eyebrow">SMART PARKING</p>
      <h1 id="result-title">Revisa tu cuenta</h1>
      <p>
        El regreso desde el pago no confirma una membresía. Inicia sesión para consultar
        el estado que el servicio de cuenta recibió y verificó.
      </p>
      <NuxtLink class="return-link" to="/cliente/membresias">
        Ir a mis membresías
      </NuxtLink>
    </section>
  </main>
</template>

<style scoped>
.result-shell { display: grid; min-height: 100vh; min-height: 100dvh; place-items: center; padding: 1.2rem; background: #f8f7fa; color: #211d28; font-family: Manrope, ui-sans-serif, system-ui, sans-serif; }
.result-card { width: min(100%, 34rem); padding: clamp(1.5rem, 5vw, 2.5rem); background: #fff; border: 1px solid #e7e1eb; border-radius: 1rem; box-shadow: 0 18px 55px rgb(35 22 48 / 7%); text-align: center; }
.result-mark { display: grid; width: 3.4rem; height: 3.4rem; margin: 0 auto 1.1rem; place-items: center; color: #674187; background: #f1ecf6; border: 1px solid #e6daed; border-radius: 50%; font-size: 1.5rem; font-weight: 850; }
.eyebrow { margin: 0 0 .45rem; color: #765b92; font-size: .65rem; font-weight: 800; letter-spacing: .12em; }
h1 { margin: 0 0 .65rem; font-size: clamp(1.45rem, 4vw, 2rem); letter-spacing: -.045em; }
.result-card > p:not(.eyebrow) { margin: 0 auto; color: #706978; font-size: .87rem; line-height: 1.6; }
.return-link { display: inline-flex; min-height: 2.8rem; align-items: center; justify-content: center; margin-top: 1.4rem; padding: .6rem 1rem; color: #fff; background: #674187; border-radius: .6rem; font-size: .82rem; font-weight: 800; text-decoration: none; }
.return-link:hover { background: #56336f; }
.return-link:focus-visible { outline: 3px solid rgb(92 58 134 / 24%); outline-offset: 3px; }
</style>
