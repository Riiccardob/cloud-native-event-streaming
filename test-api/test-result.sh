#!/bin/bash

MINIKUBE_IP=$(minikube ip)
KONG_PORT=$(kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}')
BASE_PRODUCER="http://producer.$MINIKUBE_IP.nip.io:$KONG_PORT"
BASE_METRICS="http://metrics.$MINIKUBE_IP.nip.io:$KONG_PORT"

JWT_SCRIPT="JWTtoken/gen_jwt.py"
if [ ! -f "$JWT_SCRIPT" ]; then
    echo "ERRORE: Script $JWT_SCRIPT non trovato."
    exit 1
fi
TOKEN=$(python3 "$JWT_SCRIPT" | tr -d '\r\n')

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

call_and_show() {
    METHOD=$1
    URL=$2
    DATA=$3
    
    echo -e "\n${GREEN}[$METHOD] $URL${NC}"
    
    if [ "$METHOD" == "POST" ]; then
        RESPONSE=$(curl -s -X POST "$URL" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $TOKEN" \
            -d "$DATA")
    else
        RESPONSE=$(curl -s -X GET "$URL" -H "Authorization: Bearer $TOKEN")
    fi

    # Stampa formattata se è JSON, altrimenti raw (per errori HTML)
    if echo "$RESPONSE" | grep -q "{"; then
        echo "$RESPONSE" | python3 -m json.tool
    else
        echo "$RESPONSE"
    fi
}

echo -e "${BLUE}=== POPOLAMENTO ===${NC}"
call_and_show "POST" "$BASE_PRODUCER/event/login" '{"user_id": "json_user"}'

echo -e "\nAttendo..."
sleep 2

echo -e "\n${BLUE}=== RISULTATI ===${NC}"
call_and_show "GET" "$BASE_METRICS/healthz" ""
call_and_show "GET" "$BASE_METRICS/metrics/logins" ""