from __future__ import annotations

import asyncio

from pydantic import BaseModel

from smriti.llm.router import get_router


class Person(BaseModel):
    name: str
    age: int


async def main() -> None:
    router = get_router()
    result = await router.call(
        role="intent_classification",
        prompt="Extract: 'John is 30'",
        schema=Person,
    )
    print("provider:", router.last_provider_used)
    print("result:", result.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
