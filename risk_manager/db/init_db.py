"""Database schema initialization CLI script.

Creates all tables for the configured database (SQLite async by default).
Supports zero-docker local execution.
"""

import asyncio
from risk_manager.core.config import get_settings
from risk_manager.core.logging import get_logger, setup_logging
from risk_manager.db.session import engine, init_db

logger = get_logger("risk_manager.db.init")


async def main() -> None:
    """Initialize database tables asynchronously."""
    setup_logging(level="INFO", json_format=False)
    settings = get_settings()
    logger.info("Initializing database schema at: %s", settings.DATABASE_URL)
    await init_db(engine)
    logger.info("All tables created successfully.")


if __name__ == "__main__":
    asyncio.run(main())
