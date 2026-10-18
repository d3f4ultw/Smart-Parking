import { proxyStreamVision } from '../../../../utils/proxy-stream'

export default defineEventHandler((event) => proxyStreamVision(event))
