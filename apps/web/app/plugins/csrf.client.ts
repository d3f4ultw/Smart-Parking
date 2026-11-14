/** Guarda solo en la memoria del navegador el código de seguridad de las acciones
 * administrativas y lo borra cuando deja de ser válido.
 */
export default defineNuxtPlugin(() => {
  const token = ref<string | null>(null)

  return {
    provide: {
      csrf: {
        leer: () => token.value,
        guardar: (valor: string | null) => {
          token.value = valor
        },
      },
    },
  }
})
