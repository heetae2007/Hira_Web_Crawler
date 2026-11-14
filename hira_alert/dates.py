"""게시일 해석. 시간대 없는 심평원 게시일은 한국 시간으로 본다."""

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))


def publication_date(value: str) -> date:
    value = value.strip()
    if len(value) == 17 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d%H%M%S%f").date()
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"게시일을 해석할 수 없습니다: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST).date()
