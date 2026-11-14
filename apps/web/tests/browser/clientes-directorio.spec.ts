import { expect, test } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

const clientes = Array.from({ length: 45 }, (_, indice) => {
  const codigo = `CLI-${String(indice + 1).padStart(4, '0')}`
  const estadoMembresia =
    indice % 4 === 0
      ? 'SIN_MEMBRESIA'
      : indice % 4 === 1
        ? 'ACTIVA'
        : indice % 4 === 2
          ? 'CANCELADA'
          : 'PAGO_VENCIDO'
  return {
    codigo,
    nombreCompleto: `Cliente ${String(indice + 1).padStart(2, '0')} Prueba`,
    estadoMembresia,
  }
})

test('el directorio conserva el filtro al paginar y consulta el detalle solo al abrirlo', async ({
  page,
}) => {
  const consultas: Array<{ pagina: string; estado: string; busqueda: string }> = []
  let consultasDetalle = 0
  await iniciarSesion(page)
  await page.route('**/api/v1/clientes/administracion**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/CLI-0001')) {
      consultasDetalle += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...clientes[0],
          membresia: null,
        }),
      })
      return
    }

    const pagina = url.searchParams.get('pagina') ?? '1'
    const estado = url.searchParams.get('estado') ?? 'todos'
    const busqueda = url.searchParams.get('busqueda') ?? ''
    consultas.push({ pagina, estado, busqueda })
    const filtrados = clientes.filter((cliente) => {
      const coincideEstado =
        estado === 'activa'
          ? cliente.estadoMembresia === 'ACTIVA'
          : estado === 'cancelada'
            ? cliente.estadoMembresia === 'CANCELADA'
            : estado === 'sin-membresia'
              ? ['SIN_MEMBRESIA', 'PENDIENTE', 'PAGO_VENCIDO', 'INACTIVA'].includes(
                  cliente.estadoMembresia,
                )
              : true
      const texto = `${cliente.nombreCompleto} ${cliente.codigo}`.toLocaleLowerCase('es-MX')
      return coincideEstado && textContains(texto, busqueda)
    })
    const inicio = (Number(pagina) - 1) * 10
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: filtrados.slice(inicio, inicio + 10),
        pagina: Number(pagina),
        tamanoPagina: 10,
        totalClientes: clientes.length,
        totalRegistros: filtrados.length,
        totalPaginas: Math.ceil(filtrados.length / 10),
        cursorEventos: 'cursor-prueba',
      }),
    })
  })

  await page.getByRole('link', { name: 'Clientes', exact: true }).click()
  await page.waitForURL(`${baseURL}/admin/clientes`)
  await expect(page.locator('.tabla-clientes-contenedor')).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: /CLI-[0-9]{4,}/ })).toHaveCount(10)
  await expect(page.getByText('Sin membresía', { exact: true }).first()).toBeVisible()
  expect(consultasDetalle).toBe(0)

  const botonDetalle = page.getByRole('button', { name: 'Ver detalles de Cliente 01 Prueba' })
  await botonDetalle.focus()
  await botonDetalle.click()
  await expect(page.getByRole('dialog')).toContainText('Este cliente no tiene una membresía.')
  expect(consultasDetalle).toBe(1)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(botonDetalle).toBeFocused()

  const filtro = page.getByRole('combobox', { name: 'Estado de membresía' })
  await filtro.click()
  await page.getByRole('option', { name: 'Activa', exact: true }).click()
  await expect(page).toHaveURL(/estado=activa/)
  await expect.poll(() => consultas.at(-1)).toEqual({ pagina: '1', estado: 'activa', busqueda: '' })
  await expect(page.getByRole('row').filter({ hasText: /CLI-[0-9]{4,}/ })).toHaveCount(10)

  const paginacion = page.getByRole('navigation', { name: 'Páginas de clientes' })
  await paginacion.locator('button').last().click()
  await expect(page).toHaveURL(/pagina=2.*estado=activa|estado=activa.*pagina=2/)
  await expect.poll(() => consultas.at(-1)).toEqual({ pagina: '2', estado: 'activa', busqueda: '' })
  await expect(page.getByText('Cliente 42 Prueba')).toBeVisible()
  await expect(page.getByText('Activa', { exact: true }).last()).toBeVisible()

  const busqueda = page.getByRole('textbox', { name: 'Buscar por nombre o código' })
  await busqueda.fill('CLI-0042')
  await expect(page).toHaveURL(/estado=activa.*busqueda=CLI-0042|busqueda=CLI-0042.*estado=activa/)
  await expect
    .poll(() => consultas.at(-1))
    .toEqual({
      pagina: '1',
      estado: 'activa',
      busqueda: 'CLI-0042',
    })
  await expect(page.getByRole('row').filter({ hasText: 'CLI-0042' })).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Limpiar búsqueda' })).toBeVisible()

  await busqueda.fill('Cliente 42')
  await expect
    .poll(() => consultas.at(-1))
    .toEqual({
      pagina: '1',
      estado: 'activa',
      busqueda: 'Cliente 42',
    })
  await expect(page.getByRole('row').filter({ hasText: 'CLI-0042' })).toHaveCount(1)

  await page.getByRole('button', { name: 'Limpiar búsqueda' }).click()
  await expect(page).not.toHaveURL(/busqueda=/)
  await expect.poll(() => consultas.at(-1)).toEqual({ pagina: '1', estado: 'activa', busqueda: '' })
})

function textContains(texto: string, consulta: string) {
  return !consulta || texto.includes(consulta.toLocaleLowerCase('es-MX'))
}
