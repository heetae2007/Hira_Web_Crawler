"""제목·요약 키워드 필터. include가 비어 있으면 제외어만 적용한다."""


def matches_keywords(title: str, summary: str = "", *, include=(), exclude=()) -> bool:
    haystack = f"{title}\n{summary}".lower()
    if exclude and any(k in haystack for k in exclude):
        return False
    if not include:
        return True
    return any(k in haystack for k in include)
