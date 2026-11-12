from dataclasses import dataclass


@dataclass(frozen=True)
class FormatError:
    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} {self.message}"
