from datetime import datetime

from pydantic import BaseModel


class Filters(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    app: list[str] = []
    user_role: list[str] = []
    prompt_language: list[str] = []
    topic: list[str] = []

    def where(self) -> tuple[str, list]:
        clauses, params = [], []
        if self.start:
            clauses.append("timestamp >= ?")
            params.append(self.start)
        if self.end:
            clauses.append("timestamp <= ?")
            params.append(self.end)
        for col in ("app", "user_role", "prompt_language", "topic"):
            values = getattr(self, col)
            if values:
                clauses.append(f"{col} IN ({', '.join('?' for _ in values)})")
                params.extend(values)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params
