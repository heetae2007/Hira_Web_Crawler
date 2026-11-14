"""Nexacro SSV 응답 파서 (심평원 포털 공통)."""

RS, US, ETX = "\x1e", "\x1f", "\x03"


class SSVError(ValueError):
    pass


def parse_ssv_dataset(response_text: str, dataset_name: str) -> list[dict]:
    """Parse typed SSV records; preserve HTML/newlines and reject ambiguous rows."""
    records = response_text.lstrip("\ufeff").split(RS)
    if not records or records[0].lower() != "ssv:utf-8":
        raise SSVError("UTF-8 SSV 응답이 아닙니다 (로그인/오류 HTML 확인 필요)")
    active = found = False
    columns = None
    constants = {}
    rows = []
    for record in records[1:]:
        if record.startswith("Dataset:"):
            if active:
                break
            active = record == f"Dataset:{dataset_name}"
            found = found or active
            continue
        if not active:
            for variable in record.split(US):
                key, sep, value = variable.partition("=")
                if sep and key.split(":", 1)[0] == "ErrorCode":
                    try:
                        error_code = int(value)
                    except ValueError as exc:
                        raise SSVError("잘못된 SSV ErrorCode") from exc
                    if error_code < 0:
                        raise SSVError(f"서버 SSV 오류: ErrorCode={error_code}")
            continue
        if not record:
            continue
        fields = record.split(US)
        if fields[0] == "_Const_":
            for field in fields[1:]:
                name, sep, value = field.partition("=")
                if not sep:
                    raise SSVError("잘못된 SSV 상수 컬럼")
                constants[name.split(":", 1)[0]] = "" if value == ETX else value
        elif fields[0] == "_RowType_":
            if columns is not None:
                raise SSVError("중복 SSV 컬럼 정의")
            columns = [field.split(":", 1)[0] for field in fields[1:]]
            if not all(columns) or len(set(columns)) != len(columns):
                raise SSVError("잘못된 SSV 컬럼 이름")
        else:
            if columns is None or fields[0] not in {"N", "I", "U", "D", "O"}:
                raise SSVError("SSV 컬럼 정의 또는 행 타입 확인 필요")
            values = fields[1:]
            if len(values) != len(columns):
                # Never shift fields or guess where an omitted value belongs.
                raise SSVError(f"SSV 열 개수 불일치: expected={len(columns)}, actual={len(values)}")
            if fields[0] in {"D", "O"}:
                continue
            rows.append({**constants, **dict(zip(columns, ("" if v == ETX else v for v in values)))})
    if not found:
        raise SSVError(f"Dataset:{dataset_name} 누락")
    return rows
