"""
Performance Benchmark script for Phase 8 Observability.
Measures synchronous risk scoring latency under telemetry.
"""

import asyncio
import time
import numpy as np
import uuid

from risk_manager.api.services.risk_service import score_risk_event
from risk_manager.db.session import create_engine_and_sessionmaker, init_db
from risk_manager.domain.schemas.requests import RiskScoreRequest


async def run_benchmark(n_runs: int = 50):
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine, session_maker = create_engine_and_sessionmaker(database_url=test_db_url, echo=False)
    await init_db(engine)

    latencies_ms = []

    # Warm-up run
    async with session_maker() as session:
        warmup_req = RiskScoreRequest(
            customer_id_hash="cust_warmup",
            idempotency_key="idemp_warmup",
            order_value=2500.0,
            product_category="APPAREL",
            payment_method="PREPAID",
            cod_flag=False,
            return_reason="Size issue",
        )
        await score_risk_event(session=session, request=warmup_req, background_tasks=None)
        await session.commit()

    # Benchmark runs
    for i in range(n_runs):
        req = RiskScoreRequest(
            customer_id_hash=f"cust_bench_{i % 10}",
            idempotency_key=f"idemp_bench_{uuid.uuid4().hex[:8]}",
            order_value=3200.0 + (i * 10),
            product_category="APPAREL",
            payment_method="PREPAID",
            cod_flag=False,
            return_reason="Product fit issue",
            days_since_purchase=4,
            customer_order_count=15,
            customer_return_count=1,
            customer_return_rate=0.07,
            prior_return_value=600.0,
            prior_return_frequency=0.20,
            delivery_distance_bucket="REGIONAL",
            historical_abuse_signal=0.0,
            estimated_item_recovery_value=2500.0,
        )
        t0 = time.perf_counter()
        async with session_maker() as session:
            res = await score_risk_event(session=session, request=req, background_tasks=None)
            await session.commit()
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    p50 = np.percentile(latencies_ms, 50)
    p90 = np.percentile(latencies_ms, 90)
    p95 = np.percentile(latencies_ms, 95)
    p99 = np.percentile(latencies_ms, 99)
    avg = np.mean(latencies_ms)

    print("=" * 60)
    print("PHASE 8 PERFORMANCE BENCHMARK (Synchronous Scoring + Telemetry)")
    print(f"Iterations: {n_runs}")
    print(f"Average:    {avg:.2f} ms")
    print(f"P50:        {p50:.2f} ms")
    print(f"P90:        {p90:.2f} ms")
    print(f"P95:        {p95:.2f} ms")
    print(f"P99:        {p99:.2f} ms")
    print(f"SLA Target: <= 150.00 ms (Status: {'PASSED' if p95 <= 150.0 else 'BREACHED'})")
    print("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_benchmark())
