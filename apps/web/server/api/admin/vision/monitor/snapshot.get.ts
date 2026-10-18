import { proxyAdminVisionRequest } from '../../../../utils/proxy-admin-vision'

export default defineEventHandler((event) =>
  proxyAdminVisionRequest(event, 'monitor/snapshot', 'GET', 'image'),
)
