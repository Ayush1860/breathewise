"""DynamoDB single-table storage (spec §10).

Keys: pk/sk strings, `ttl` epoch seconds. Pollutant values and documents are stored as
JSON strings to avoid DynamoDB's Decimal conversions.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.schemas import (
    ForecastHour,
    ForecastResponse,
    Pollutant,
    Quantiles,
    Source,
    SourceHealth,
)

TTL = timedelta(days=30)
SOURCE_PRIORITY = {Source.CAMS_MODEL: 0, Source.OPENAQ: 1, Source.CPCB: 2}


@dataclass(frozen=True)
class Observation:
    station_id: str
    time: datetime  # start of the UTC hour
    source: Source
    values: dict[Pollutant, float]  # ug/m3, CO in mg/m3


@dataclass(frozen=True)
class ForecastLogEntry:
    station_id: str
    model_version: str
    issued_at: datetime
    hour: ForecastHour

    @property
    def horizon_h(self) -> int:
        return self.hour.horizon_h

    @property
    def pm25(self) -> Quantiles:
        return self.hour.pm25


def create_table(dynamodb: Any, name: str) -> Any:
    """Create the table (tests and local runs; production uses the SAM template)."""
    return dynamodb.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _station_pk(station_id: str) -> str:
    return f"STATION#{station_id}"


def _encode_values(values: dict[Pollutant, float]) -> str:
    return json.dumps({p.value: v for p, v in values.items()}, sort_keys=True)


def _to_observation(item: dict[str, Any]) -> Observation:
    return Observation(
        station_id=item["pk"].removeprefix("STATION#"),
        time=datetime.fromisoformat(item["time"]),
        source=Source(item["source"]),
        values={Pollutant(k): v for k, v in json.loads(item["values"]).items()},
    )


def _conditional_put(table: Any, item: dict[str, Any], **condition: Any) -> bool:
    try:
        table.put_item(Item=item, **condition)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


class Store:
    def __init__(self, table: Any, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.table = table
        self.now = now

    def _ttl(self) -> int:
        return int((self.now() + TTL).timestamp())

    def _observation_item(self, obs: Observation, sk: str) -> dict[str, Any]:
        return {
            "pk": _station_pk(obs.station_id),
            "sk": sk,
            "time": obs.time.isoformat(),
            "source": obs.source.value,
            "priority": SOURCE_PRIORITY[obs.source],
            "values": _encode_values(obs.values),
            "ingested_at": self.now().isoformat(),
        }

    def put_observation(self, obs: Observation) -> bool:
        """Upsert; a lower-priority source never overwrites a higher one."""
        item = self._observation_item(obs, f"OBS#{obs.time.isoformat()}") | {"ttl": self._ttl()}
        return _conditional_put(
            self.table,
            item,
            ConditionExpression="attribute_not_exists(pk) OR priority <= :p",
            ExpressionAttributeValues={":p": SOURCE_PRIORITY[obs.source]},
        )

    def update_latest(self, obs: Observation) -> bool:
        """LATEST only moves forward in time."""
        return _conditional_put(
            self.table,
            self._observation_item(obs, "LATEST"),
            ConditionExpression="attribute_not_exists(pk) OR #t <= :t",
            ExpressionAttributeNames={"#t": "time"},
            ExpressionAttributeValues={":t": obs.time.isoformat()},
        )

    def observations(self, station_id: str, since: datetime) -> list[Observation]:
        response = self.table.query(
            KeyConditionExpression=Key("pk").eq(_station_pk(station_id))
            & Key("sk").between(f"OBS#{since.isoformat()}", "OBS#~")
        )
        return [_to_observation(i) for i in response["Items"]]

    def latest(self, station_id: str) -> Observation | None:
        item = self.table.get_item(Key={"pk": _station_pk(station_id), "sk": "LATEST"}).get("Item")
        return _to_observation(item) if item else None

    def record_health(self, source: Source, ok: bool, error: str | None = None) -> None:
        stamp = self.now().isoformat()
        if ok:
            update = "SET last_success_at = :t"
            values: dict[str, Any] = {":t": stamp}
        else:
            update = "SET last_failure_at = :t, last_error = :e"
            values = {":t": stamp, ":e": (error or "unknown error")[:500]}
        self.table.update_item(
            Key={"pk": "META", "sk": f"HEALTH#{source.value}"},
            UpdateExpression=update,
            ExpressionAttributeValues=values,
        )

    def health(self) -> list[SourceHealth]:
        response = self.table.query(
            KeyConditionExpression=Key("pk").eq("META") & Key("sk").begins_with("HEALTH#")
        )
        return [
            SourceHealth(
                source=Source(item["sk"].removeprefix("HEALTH#")),
                last_success_at=item.get("last_success_at"),
                last_failure_at=item.get("last_failure_at"),
                last_error=item.get("last_error"),
            )
            for item in response["Items"]
        ]

    def put_forecast(self, doc: ForecastResponse) -> None:
        """Store the current forecast and append every hour to the forecast log."""
        pk = _station_pk(doc.station_id)
        issued = doc.issued_at.isoformat()
        with self.table.batch_writer() as batch:
            batch.put_item(Item={"pk": pk, "sk": "FC#CURRENT", "doc": doc.model_dump_json()})
            for hour in doc.hours:
                batch.put_item(
                    Item={
                        "pk": pk,
                        "sk": f"FCLOG#{doc.model_version}#{hour.target_time.isoformat()}#{issued}",
                        "model_version": doc.model_version,
                        "issued_at": issued,
                        "hour": hour.model_dump_json(),
                        "ttl": self._ttl(),
                    }
                )

    def current_forecast(self, station_id: str) -> ForecastResponse | None:
        key = {"pk": _station_pk(station_id), "sk": "FC#CURRENT"}
        item = self.table.get_item(Key=key).get("Item")
        return ForecastResponse.model_validate_json(item["doc"]) if item else None

    def forecast_log(
        self, station_id: str, model_version: str, since: datetime
    ) -> list[ForecastLogEntry]:
        prefix = f"FCLOG#{model_version}#"
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(_station_pk(station_id))
            & Key("sk").between(f"{prefix}{since.isoformat()}", f"{prefix}~")
        }
        while True:
            response = self.table.query(**kwargs)
            items.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return [
            ForecastLogEntry(
                station_id=station_id,
                model_version=item["model_version"],
                issued_at=datetime.fromisoformat(item["issued_at"]),
                hour=ForecastHour.model_validate_json(item["hour"]),
            )
            for item in items
        ]
