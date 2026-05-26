"""Streaming CSV export utility (Phase 2B.7).

- UTF-8 with BOM (Excel compat)
- No full materialisation in memory — yields each row as it's produced
- Cleans newlines/commas/quotes in values via the stdlib csv module
- Sets Content-Disposition so browser downloads with a filename

Usage:
    return stream_csv(
        filename="revenue_2026-03.csv",
        header=["date", "revenue_rupees"],
        rows=((r.period, r.revenue / 100) for r in result),
    )
"""
from __future__ import annotations
import csv
import io
from typing import Any, Iterable, Iterator

from fastapi.responses import StreamingResponse


def _row_to_csv(writer: csv.writer, buf: io.StringIO, row: Iterable[Any]) -> str:
    writer.writerow(["" if v is None else v for v in row])
    out = buf.getvalue()
    buf.seek(0)
    buf.truncate(0)
    return out


def stream_csv(
    *,
    filename: str,
    header: list[str],
    rows: Iterable[Iterable[Any]],
) -> StreamingResponse:
    """Return a StreamingResponse that yields a CSV file.

    The generator produces bytes (UTF-8) so large reports don't balloon memory.
    """
    def generate() -> Iterator[bytes]:
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
        # BOM so Excel auto-detects UTF-8 & renders ₹ / non-ASCII names correctly.
        yield "\ufeff".encode("utf-8")
        yield _row_to_csv(writer, buf, header).encode("utf-8")
        for r in rows:
            yield _row_to_csv(writer, buf, r).encode("utf-8")

    safe_name = filename.replace('"', '').replace("\n", "")
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "Content-Type": "text/csv; charset=utf-8",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8", headers=headers)
