# Cron setup — etsy3d

## Daily trend scan

Dodaj do crontab (`crontab -e`):

```
# Codzienny skan trendów o 7:00 — tworzy max 3 nowe drafty
0 7 * * * .venv/bin/python cli.py trend-scan --max-new 3 >> logs/cron.log 2>&1

# Nocny restock check o 00:00
0 0 * * * cd /home/dell/etsy3d && .venv/bin/python cli.py restock-check >> logs/cron.log 2>&1
```

## Webhook Etsy (sprzedaż → aktualizacja stanu)

1. Ustaw `ETSY_WEBHOOK_SECRET` w `.env`
2. Uruchom serwer: `python cli.py webhook-serve --port 8765`
3. Skonfiguruj URL callbacku w Etsy Developer: `https://<twoj-host>:8765/etsy/webhook`

Serwer obsługuje:
- `POST /etsy/webhook` — zdarzenia Etsy (RECEIPT_PAID)
- `GET  /health`        — health check

## Zmienne środowiskowe (Faza 5)

```
ETSY_WEBHOOK_SECRET=   # sekret HMAC do weryfikacji podpisów Etsy
```
