#!/usr/bin/env sh

set -u

check_url() {
    name=$1
    url=$2
    status=$(curl --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' --connect-timeout 3 --max-time 10 "$url" 2>/dev/null) || status=''

    if [ "$status" = '200' ]; then
        printf 'PASS %s HTTP 200\n' "$name"
        return 0
    fi

    printf 'FAIL %s HTTP %s\n' "$name" "${status:-unreachable}"
    return 1
}

failed=0
check_url 'Web' 'http://localhost:3000/login' || failed=1
check_url 'API' 'http://localhost:8000/health' || failed=1

if [ -t 0 ]; then
    printf 'Presione Enter para cerrar...'
    IFS= read -r _
fi

exit "$failed"
