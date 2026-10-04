export type TipoToastAdmin = 'success' | 'error'

export interface ToastAdmin {
  id: number
  tipo: TipoToastAdmin
  mensaje: string
}

export function useAdminToasts() {
  const toasts = useState<ToastAdmin[]>('admin-toasts', () => [])
  const siguienteId = useState('admin-toasts-siguiente-id', () => 0)

  function mostrarToast(mensaje: string, tipo: TipoToastAdmin = 'success') {
    const id = siguienteId.value + 1
    siguienteId.value = id
    toasts.value = [...toasts.value, { id, tipo, mensaje }].slice(-3)
  }

  function descartarToast(id: number) {
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  function limpiarToasts() {
    toasts.value = []
  }

  return { toasts, mostrarToast, descartarToast, limpiarToasts }
}
