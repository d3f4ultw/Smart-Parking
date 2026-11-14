import { defineConfig } from '@playwright/test'
import configuracion from './playwright.config'

// La aceptación física pertenece a una fase separada, incluso si alguien
// suministra variables de entorno que antes habilitaban ese spec.
export default defineConfig({
  ...configuracion,
  testIgnore: ['**/*fisica*.spec.ts', '**/*fisico*.spec.ts'],
})
