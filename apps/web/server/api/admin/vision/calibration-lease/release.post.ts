import { proxyAdminVisionRequest } from '../../../../utils/proxy-admin-vision'

export default defineEventHandler((event) =>
  proxyAdminVisionRequest(
    event,
    'calibration-lease/release',
    'POST',
    'json',
    { abortOnClientDisconnect: false },
  ),
)
