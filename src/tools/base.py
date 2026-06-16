from abc import ABC, abstractmethod


class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def definition(self) -> dict: ...

    @abstractmethod
    async def execute(self, args: dict, request) -> dict: ...
