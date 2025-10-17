import asyncio

import pytest

from goldenverba.server.db import Database
from goldenverba.server.part_numbers import (
    PartNumberNotFoundError,
    PartNumberService,
    PartNumberValidationError,
)
from goldenverba.server.rules import load_rules


@pytest.fixture
async def part_service():
    db = Database(url="sqlite+aiosqlite:///:memory:")
    await db.connect()
    rules = load_rules()
    service = PartNumberService(db, rules)
    yield service
    await db.disconnect()


@pytest.mark.asyncio
async def test_generate_sequence(part_service: PartNumberService):
    first = await part_service.generate_part(series="730", created_by="tester", idempotency_key="seq-1")
    second = await part_service.generate_part(series="730", created_by="tester", idempotency_key="seq-2")

    assert first.part_no == "730-00001-00"
    assert second.part_no == "730-00002-00"


@pytest.mark.asyncio
async def test_idempotent_reuse(part_service: PartNumberService):
    key = "idem-730"
    first = await part_service.generate_part(series="730", created_by="tester", idempotency_key=key)
    retry = await part_service.generate_part(series="730", created_by="tester", idempotency_key=key)

    assert retry.part_no == first.part_no
    assert retry.serial == first.serial


@pytest.mark.asyncio
async def test_series_seed_values(part_service: PartNumberService):
    mat = await part_service.generate_part(series="200", created_by="tester", idempotency_key="seed-200")
    bond = await part_service.generate_part(series="730", created_by="tester", idempotency_key="seed-730")

    assert mat.serial == 5001
    assert bond.serial == 1


@pytest.mark.asyncio
async def test_revision_override(part_service: PartNumberService):
    result = await part_service.generate_part(
        series="725",
        created_by="tester",
        revision="05",
        idempotency_key="rev-725",
    )

    assert result.revision == "05"
    assert result.part_no.endswith("-05")


@pytest.mark.asyncio
async def test_unknown_series_raises(part_service: PartNumberService):
    with pytest.raises(PartNumberValidationError):
        await part_service.generate_part(series="999", created_by="tester", idempotency_key="bad-series")


@pytest.mark.asyncio
async def test_concurrent_generation(part_service: PartNumberService):
    async def _issue(idx: int):
        return await part_service.generate_part(
            series="725",
            created_by="tester",
            idempotency_key=f"con-{idx}",
        )

    results = await asyncio.gather(*[_issue(i) for i in range(1, 21)])
    serials = sorted(part.serial for part in results)
    assert serials == list(range(1, 21))


@pytest.mark.asyncio
async def test_get_part_roundtrip(part_service: PartNumberService):
    generated = await part_service.generate_part(series="735", created_by="tester", idempotency_key="get-1")
    record = await part_service.get_part(generated.part_no)

    assert record["part_no"] == generated.part_no
    assert int(record["serial"]) == generated.serial
    assert record["revision"] == generated.revision


@pytest.mark.asyncio
async def test_get_part_missing(part_service: PartNumberService):
    with pytest.raises(PartNumberNotFoundError):
        await part_service.get_part("730-99999-00")
