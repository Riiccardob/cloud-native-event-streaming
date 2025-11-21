#!/bin/bash

# --- CONFIGURAZIONE ---
MINIKUBE_IP=$(minikube ip)
# Trova automaticamente la porta di Kong
KONG_PORT=$(kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}')

BASE_PRODUCER="http://producer.$MINIKUBE_IP.nip.io:$KONG_PORT"
BASE_METRICS="http://metrics.$MINIKUBE_IP.nip.io:$KONG_PORT"
# IL TUO NUOVO TOKEN (Scadenza 2025)
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJleGFtLWNsaWVudC1rZXkiLCJzdWIiOiJlbmVhIiwicm9sZSI6ImV4YW0tY2xpZW50IiwiZXhwIjoxNzYzNjU2NjAwfQ.XdORbJLNoePsoVb3VjfTawFeNOL3fO-U3g4PycQT56s"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== CONFIGURAZIONE RILEVATA ===${NC}"
echo "Producer: $BASE_PRODUCER"
echo "Metrics:  $BASE_METRICS"
echo "----------------------------------------"

# Funzione per chiamare e stampare
call_and_show() {
    METHOD=$1
    URL=$2
    DATA=$3
    
    echo -e "\n${GREEN}[$METHOD] $URL${NC}"
    
    if [ "$METHOD" == "POST" ]; then
        # Per le POST stampiamo lo status e un breve estratto
        RESPONSE=$(curl -s -X POST "$URL" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $TOKEN" \
            -d "$DATA")
        echo "$RESPONSE" | python3 -m json.tool
    else
        # Per le GET stampiamo tutto il JSON formattato
        RESPONSE=$(curl -s -X GET "$URL" -H "Authorization: Bearer $TOKEN")
        
        # Controllo se è un errore HTML (es. 404/503 di Kong/Nginx) o JSON valido
        if [[ "$RESPONSE" == *"<html>"* ]]; then
             echo "ERRORE (Risposta HTML, probabile errore Gateway/Ingress)"
             echo "$RESPONSE" | head -n 5
        else
             echo "$RESPONSE" | python3 -m json.tool
        fi
    fi
}

# --- 1. INSERIMENTO DATI (Opzionale, per avere qualcosa da leggere) ---
echo -e "\n${BLUE}=== POPOLAMENTO DATI (PRODUCER) ===${NC}"
call_and_show "POST" "$BASE_PRODUCER/event/login" '{"user_id": "mario_rossi"}'
call_and_show "POST" "$BASE_PRODUCER/event/quiz" '{"user_id": "mario_rossi", "quiz_id": "architettura_k8s", "course_id": "cloud", "score": 28}'

echo -e "\nAttendo 2 secondi per processamento Kafka..."
sleep 2

# --- 2. LETTURA DATI (METRICS) ---
echo -e "\n${BLUE}=== RISULTATI API (METRICS) ===${NC}"

# Ora healthz dovrebbe funzionare se hai aggiornato l'ingress
call_and_show "GET" "$BASE_METRICS/healthz" ""

echo -e "\n--- Logins ---"
call_and_show "GET" "$BASE_METRICS/metrics/logins" ""

echo -e "\n--- Success Rate Quiz ---"
call_and_show "GET" "$BASE_METRICS/metrics/quiz/success-rate" ""

echo -e "\n--- Activity Trend ---"
call_and_show "GET" "$BASE_METRICS/metrics/activity/last7days" ""