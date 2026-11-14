import http from 'node:http'

const upstream = new URL(process.env.WEB_PROXY_TARGET ?? process.env.TEST_WEB_UPSTREAM ?? 'http://web:3000')
const port = Number(process.env.TEST_PROXY_PORT ?? '3000')

const proxy = http.createServer((request, response) => {
  const forwarded = http.request(
    {
      hostname: upstream.hostname,
      port: upstream.port || 80,
      path: request.url ?? '/',
      method: request.method,
      headers: { ...request.headers, host: upstream.host },
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers)
      upstreamResponse.pipe(response)
    },
  )

  forwarded.on('error', () => {
    if (!response.headersSent) response.writeHead(502)
    response.end()
  })
  request.on('aborted', () => forwarded.destroy())
  response.on('close', () => {
    if (!response.writableEnded) forwarded.destroy()
  })
  request.pipe(forwarded)
})

proxy.on('upgrade', (request, socket, head) => {
  const forwarded = http.request({
    hostname: upstream.hostname,
    port: upstream.port || 80,
    path: request.url ?? '/',
    method: request.method,
    headers: { ...request.headers, host: upstream.host },
  })

  forwarded.on('upgrade', (response, upstreamSocket, upstreamHead) => {
    const headers = Object.entries(response.headers).map(([name, value]) => {
      const rendered = Array.isArray(value) ? value.join(', ') : value
      return `${name}: ${rendered}`
    })
    socket.write(
      [`HTTP/${response.httpVersion} ${response.statusCode} ${response.statusMessage}`, ...headers, '', ''].join(
        '\r\n',
      ),
    )
    if (upstreamHead.length) socket.write(upstreamHead)
    if (head.length) upstreamSocket.write(head)
    upstreamSocket.pipe(socket)
    socket.pipe(upstreamSocket)
  })

  forwarded.on('response', (response) => {
    socket.write(`HTTP/${response.httpVersion} ${response.statusCode} ${response.statusMessage}\r\n`)
    for (const [name, value] of Object.entries(response.headers)) {
      const rendered = Array.isArray(value) ? value.join(', ') : value
      socket.write(`${name}: ${rendered}\r\n`)
    }
    socket.write('\r\n')
    response.pipe(socket)
  })
  forwarded.on('error', () => socket.destroy())
  forwarded.end()
})

proxy.listen(port, '127.0.0.1')
