import asyncio
from app.db import SessionLocal
from app.models import Meeting
from sqlalchemy import select

async def check():
    async with SessionLocal() as s:
        res = await s.execute(select(Meeting))
        meetings = res.scalars().all()
        print(f"Found {len(meetings)} meetings")
        for m in meetings:
            print(f"ID: {m.id}, Title: {m.title}, State: {m.state}")

if __name__ == "__main__":
    asyncio.run(check())
