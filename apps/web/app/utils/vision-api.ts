export type ZonaVisionWeb = {
  vision_zone_id: string
  numero: number
  cajon_id: number
  polygon: [number, number][]
}

export type RespuestaConfiguracionVision = {
  revision: number
  next_c_number: number
  zones: ZonaVisionWeb[]
}

export type ZonaVisionBorrador = {
  vision_zone_id: string
  numero: number | null
  polygon: [number, number][]
}
