#!/usr/bin/env python
"""Convenience runner script for database initialization."""

import asyncio
from risk_manager.db.init_db import main

if __name__ == "__main__":
    asyncio.run(main())
