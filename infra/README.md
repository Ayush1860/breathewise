# Infrastructure

AWS SAM stack `breathewise-prod` (ap-south-1), in the repo owner's account only.

## Build and deploy

```bash
uv run --with pip python infra/scripts/build.py      # stage code + build layers into build/
sam deploy --template-file infra/template.yaml --config-file samconfig.toml
```

Run `sam deploy` from `infra/`, or pass `--config-file infra/samconfig.toml`. A deploy needs a reviewed resource list and cost estimate first.

## Resources

| Resource | Purpose |
|---|---|
| DynamoDB table (on-demand, TTL `ttl`) | Observations, latest reading, forecasts, forecast log, health |
| S3 bucket (private, SSE, `raw/` expires after 30 d) | Raw source payloads, model artefacts |
| `IngestFunction` + EventBridge Scheduler `cron(15 * * * ? *)` | Hourly fallback-chain ingest; invokes the forecast asynchronously |
| `ForecastFunction` (common + ml layers) | Forecast and forecast log |
| `ApiFunction` (FastAPI via Mangum) + HTTP API (50 rps, burst 100) | Public API; refresh lock and ingest trigger |
| CloudFront distribution (cache policy honours origin `Cache-Control`, max 300 s) | Public base URL (`ApiUrl` output) |
| Warm-up schedule `rate(5 minutes)` (parameter `WarmupState`, default `DISABLED`) | Enable on event day |
| `ProbeFunction` (ml layer) | G1 packaging probe; remove after it passes |
| `CommonLayer` (pydantic, fastapi, mangum), `MlLayer` (lightgbm, numpy, scipy, libgomp) | Dependencies |
| Log groups (14 d) and 2 error alarms | Monitoring |

## Demo drill

Simulate source outages without touching code:

```bash
sam deploy ... --parameter-overrides ForceFail=cpcb,openaq
```

## Budget alert ($1)

```bash
aws budgets create-budget --account-id <ACCOUNT_ID> --budget '{"BudgetName":"breathewise-1usd","BudgetLimit":{"Amount":"1","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"<YOUR_EMAIL>"}]},{"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"<YOUR_EMAIL>"}]}]'
```

## Event day

```bash
sam deploy ... --parameter-overrides WarmupState=ENABLED CorsOrigins=https://<amplify-domain>,http://localhost:5173
```
