"""일기장(Firestore의 diaries)을 살펴보고, 예전 묵상을 지금의 구조에 맞추는 도구.

쓰는 법 (프로젝트 폴더에서):
  .venv/bin/python -m tools.diaries backup   --key 열쇠파일.json     모든 묵상을 파일로 내려받는다 (읽기만 한다)
  .venv/bin/python -m tools.diaries inspect  --key 열쇠파일.json     구조를 살펴보고 알려 준다 (읽기만 한다)
  .venv/bin/python -m tools.diaries upgrade  --key 열쇠파일.json     빠진 항목을 채우면 무엇이 바뀌는지 보여 준다 (읽기만 한다)
  .venv/bin/python -m tools.diaries upgrade  --key 열쇠파일.json --apply --backup backup/파일.json
                                                                    실제로 채운다. 더하기만 하고, 채운 뒤 사본과 대조한다
  .venv/bin/python -m tools.diaries drop-summary --key 열쇠파일.json [--apply --backup backup/파일.json]
                                                                    적용 진리로 옮겨진 truthSummary 항목을 없앤다

--apply가 없으면 어떤 명령도 DB를 바꾸지 않는다. 화면에는 묵상의 글을 길게 찍지 않는다.
"""
import argparse
import datetime
import json
import re
import sys
from collections import Counter
from pathlib import Path

from diary.legacy import missing_fields, position
from diary.schema import DATE, FIELDS, TIME
from diary.store import RECORDS

CURRENT = set(FIELDS) | {"uid", "deleted"}          # 지금의 구조: 19개 항목
OLD_FIELDS = ["date", "meditation_time", "passage", "prayer", "observation", "background",
              "interpretation", "truth", "application", "truthSummary", "uid"]


def read_all(db):
    """diaries의 모든 문서를 {번호: 항목들}로 읽는다."""
    return {snapshot.id: snapshot.to_dict() for snapshot in db.collection(RECORDS).stream()}


def backup(db, folder="backup"):
    docs = read_all(db)
    Path(folder).mkdir(exist_ok=True)
    path = Path(folder) / f"diaries-{datetime.datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(docs, ensure_ascii=False, indent=1, sort_keys=True, default=str), encoding="utf-8")
    again = json.loads(path.read_text(encoding="utf-8"))          # 적은 것을 다시 읽어 수를 맞춰 본다
    if len(again) != len(docs):
        raise SystemExit("사본을 다시 읽었더니 문서 수가 다릅니다. 사본을 믿지 마세요.")
    return path, len(docs)


def _truth_lines(text):
    return [re.sub(r"^\s*(?:[-•]|\d+[.)])\s*", "", line).strip() for line in (text or "").splitlines() if line.strip()]


def _squeeze(text):
    return re.sub(r"[\s.,!?]", "", text or "")


def inspect(db):
    """구조를 살펴본 결과를 줄글로 돌려준다. DB는 읽기만 한다."""
    docs = read_all(db)
    out = [f"diaries의 문서: {len(docs)}개"]
    owners = Counter(doc.get("uid", "(uid 없음)") for doc in docs.values())
    out.append("사람별: " + ", ".join(f"{uid[:8]}… {n}개" for uid, n in owners.most_common()))

    shapes = Counter(tuple(sorted(doc)) for doc in docs.values())
    out.append(f"\n항목의 짜임이 {len(shapes)}가지입니다.")
    for shape, n in shapes.most_common():
        extra, lacking = sorted(set(shape) - CURRENT), sorted(CURRENT - set(shape))
        note = "지금의 구조와 같음" if not extra and not lacking else \
            f"지금의 구조에 없는 항목: {', '.join(extra) or '없음'} / 빠진 항목: {', '.join(lacking) or '없음'}"
        out.append(f"- {n}개: 항목 {len(shape)}개. {note}")

    unreadable = [(rid, doc.get("passage")) for rid, doc in docs.items()
                  if "book" not in doc and position(doc.get("passage")) is None]
    out.append(f"\n본문(passage)에서 책, 장, 절을 읽어 내지 못한 문서: {len(unreadable)}개")
    for text, n in Counter(str(passage) for _, passage in unreadable).most_common(40):
        out.append(f"- {text!r} ({n}개)")

    bad_dates = [rid for rid, doc in docs.items() if not (isinstance(doc.get("date"), str) and DATE.fullmatch(doc["date"]))]
    bad_times = [rid for rid, doc in docs.items()
                 if not (isinstance(doc.get("meditation_time"), str) and TIME.fullmatch(doc["meditation_time"]))]
    out.append(f"\n날짜의 모양이 다른 문서: {len(bad_dates)}개 {bad_dates[:5]}")
    out.append(f"시각의 모양이 다른 문서: {len(bad_times)}개 {bad_times[:5]}")
    not_text = Counter(field for doc in docs.values() for field in OLD_FIELDS
                       if field in doc and not isinstance(doc[field], str))
    out.append("글이 아닌 값이 든 항목: " + (", ".join(f"{f} {n}개" for f, n in not_text.items()) or "없음"))
    same_day = Counter((doc.get("uid"), doc.get("date")) for doc in docs.values())
    out.append(f"같은 사람이 같은 날 두 번 이상 묵상한 날: {sum(1 for n in same_day.values() if n > 1)}일")
    years = Counter(str(doc.get("date", ""))[:4] for doc in docs.values())
    out.append("해마다: " + ", ".join(f"{year}년 {n}개" for year, n in sorted(years.items())))

    # truth에는 여러 진리가, truthSummary에는 적용 진리가 들어 있다. 실제로 그런지 센다
    kinds, many = Counter(), 0
    for doc in docs.values():
        if "truthSummary" not in doc:
            continue
        lines, summary = _truth_lines(doc.get("truth")), doc.get("truthSummary")
        many += len(lines) > 1
        if not isinstance(summary, str) or not summary.strip():
            kinds["비어 있음"] += 1
        elif _squeeze(summary) in {_squeeze(line) for line in lines}:
            kinds["truth의 한 줄과 같음"] += 1
        elif any(_squeeze(summary) in _squeeze(line) or _squeeze(line) in _squeeze(summary) for line in lines):
            kinds["truth의 한 줄에 들어 있거나 그 줄을 품음"] += 1
        else:
            kinds["truth에 없는 문장"] += 1
    out.append(f"\ntruthSummary가 있는 문서: {sum(kinds.values())}개 (그 가운데 truth가 두 줄 이상인 문서 {many}개)")
    out += [f"- {kind}: {n}개" for kind, n in kinds.most_common()]
    return "\n".join(out)


def plan_upgrade(docs):
    """문서마다 더할 항목을 정한다. (더할 것, 본문을 읽지 못한 문서 번호들)"""
    changes, unreadable = {}, []
    for rid, doc in docs.items():
        add = missing_fields(doc)
        if add is None:
            unreadable.append(rid)
        elif add:
            changes[rid] = add
    return changes, unreadable


def upgrade(db, apply=False, backup_path=None):
    docs = read_all(db)
    changes, unreadable = plan_upgrade(docs)
    out = [f"문서 {len(docs)}개 가운데: 채울 문서 {len(changes)}개, 이미 맞는 문서 {len(docs) - len(changes) - len(unreadable)}개, "
           f"본문을 읽지 못해 그대로 두는 문서 {len(unreadable)}개"]
    out.append("더하는 항목: " + (", ".join(f"{f} {n}개" for f, n in
                                            Counter(f for add in changes.values() for f in add).most_common()) or "없음"))
    for rid in unreadable[:40]:
        out.append(f"- 읽지 못함: {rid} {docs[rid].get('passage')!r}")
    if not apply:
        out.append("\n아직 아무것도 바꾸지 않았습니다. 실제로 채우려면 --apply 와 --backup 사본파일 을 붙여 다시 실행합니다.")
        return "\n".join(out)

    if not backup_path or not Path(backup_path).exists():
        raise SystemExit("--apply 에는 --backup 사본파일 이 필요합니다. 먼저 backup 을 실행하세요.")
    saved = json.loads(Path(backup_path).read_text(encoding="utf-8"))
    if set(saved) != set(docs) or any(json.loads(json.dumps(docs[rid], default=str)) != saved[rid] for rid in docs):
        raise SystemExit("사본이 지금의 DB와 다릅니다. backup 을 다시 실행한 뒤 그 파일로 해 주세요.")

    for rid, add in changes.items():
        already = set(add) & set(docs[rid])
        if already:                                    # 더하기만 한다. 이미 있는 항목은 절대 쓰지 않는다
            raise SystemExit(f"{rid}: 이미 있는 항목을 쓰려고 했습니다 ({already}). 멈춥니다.")
        db.collection(RECORDS).document(rid).update(add)

    after = read_all(db)                               # 다시 읽어, 예전 항목이 그대로인지 사본과 대조한다
    problems = []
    for rid, before in saved.items():
        now = json.loads(json.dumps(after.get(rid, {}), default=str))
        if any(now.get(field) != value for field, value in before.items()):
            problems.append(f"{rid}: 예전 항목이 달라졌습니다")
        if rid in changes and any(now.get(field) != value for field, value in changes[rid].items()):
            problems.append(f"{rid}: 채운 항목이 들어가지 않았습니다")
    out.append(f"\n{len(changes)}개 문서에 항목을 채웠습니다. 다시 읽어 사본과 대조했습니다: " +
               ("예전 항목은 모두 그대로입니다." if not problems else f"문제 {len(problems)}건\n" + "\n".join(problems[:20])))
    shapes = Counter(tuple(sorted(doc)) for doc in after.values())
    out.append(f"이제 항목의 짜임은 {len(shapes)}가지입니다.")
    return "\n".join(out)


def drop_summary(db, apply=False, backup_path=None):
    """적용 진리로 옮겨진 truthSummary를 없앤다. applied_truth와 내용이 같은 문서에서만 없앤다."""
    docs = read_all(db)
    ready = [rid for rid, doc in docs.items() if "truthSummary" in doc and doc.get("applied_truth") == doc["truthSummary"]]
    differ = [rid for rid, doc in docs.items() if "truthSummary" in doc and doc.get("applied_truth") != doc["truthSummary"]]
    out = [f"truthSummary가 applied_truth와 같아 없앨 수 있는 문서: {len(ready)}개",
           f"둘이 달라서 그대로 두는 문서: {len(differ)}개 {differ[:10]}"]
    if not apply:
        out.append("\n아직 아무것도 바꾸지 않았습니다. 실제로 없애려면 --apply 와 --backup 사본파일 을 붙여 다시 실행합니다.")
        return "\n".join(out)
    if not backup_path or not Path(backup_path).exists():
        raise SystemExit("--apply 에는 --backup 사본파일 이 필요합니다.")
    saved = json.loads(Path(backup_path).read_text(encoding="utf-8"))
    if any(rid not in saved or saved[rid].get("truthSummary") != docs[rid]["truthSummary"] for rid in ready):
        raise SystemExit("사본에 없는 truthSummary가 있습니다. backup 을 다시 실행한 뒤 그 파일로 해 주세요.")
    from google.cloud.firestore import DELETE_FIELD
    for rid in ready:
        db.collection(RECORDS).document(rid).update({"truthSummary": DELETE_FIELD})
    left = sum(1 for doc in read_all(db).values() if "truthSummary" in doc)
    out.append(f"\n{len(ready)}개 문서에서 truthSummary를 없앴습니다. 아직 남은 문서: {left}개")
    return "\n".join(out)


def connect(key_path):
    import firebase_admin
    from firebase_admin import credentials, firestore
    return firestore.client(firebase_admin.initialize_app(credentials.Certificate(key_path)))


def main():
    parser = argparse.ArgumentParser(description="일기장을 살펴보고 예전 묵상을 지금의 구조에 맞춘다")
    parser.add_argument("command", choices=["backup", "inspect", "upgrade", "drop-summary"])
    parser.add_argument("--key", required=True, help="서비스 계정 키 파일 (JSON)")
    parser.add_argument("--apply", action="store_true", help="실제로 바꾼다. 없으면 보여 주기만 한다")
    parser.add_argument("--backup", help="대조할 사본 파일 (backup 명령이 만든 것)")
    args = parser.parse_args()
    db = connect(args.key)
    if args.command == "backup":
        path, count = backup(db)
        print(f"문서 {count}개를 {path} 에 내려받았습니다. 이 파일에는 묵상의 글이 들어 있습니다. Git에 올리지 않습니다.")
    elif args.command == "inspect":
        print(inspect(db))
    elif args.command == "upgrade":
        print(upgrade(db, args.apply, args.backup))
    else:
        print(drop_summary(db, args.apply, args.backup))


if __name__ == "__main__":
    sys.exit(main())
