"""조회 점검 (DB/Telegram 사용 안 함).

    python -m hira_alert.check main
    python -m hira_alert.check eform [--pages 2]
    python -m hira_alert.check legacy --bbs-id BBSMSTR_000000000675 [--page 1]
"""

import argparse
import json
from dataclasses import asdict

from .sources import biz_legacy, biz_main, eform


def _dump(data) -> None:
    print(json.dumps(data, ensure_ascii=True))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hira_alert.check", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="target", required=True)
    sub.add_parser("main", help="업무포털 메인 공지사항")
    p = sub.add_parser("eform", help="e-Form 공지사항")
    p.add_argument("--pages", type=int, default=1, choices=range(1, 11))
    p = sub.add_parser("legacy", help="업무포털 게시판 직접 POST")
    p.add_argument("--bbs-id", required=True)
    p.add_argument("--page", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.target == "main":
            notices = biz_main.fetch_main_notices()
            _dump({"count": len(notices), "notices": [asdict(n) for n in notices]})
        elif args.target == "eform":
            notices = eform.fetch_notices(pages=args.pages)
            _dump({"count": len(notices), "notices": [asdict(n) for n in notices]})
        else:
            rows = biz_legacy.fetch_biz_page(args.bbs_id, args.page)
            posts = [biz_legacy.BizPost.from_row(row, args.bbs_id) for row in rows]
            _dump({"bbs_id": args.bbs_id, "page": args.page, "count": len(posts),
                   "columns": list(rows[0]) if rows else [],
                   "gosi_count": sum(bool(p.gosi_numbers) for p in posts)})
    except Exception as exc:
        print(f"{args.target} check failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
