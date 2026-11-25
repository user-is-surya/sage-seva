"""Demo: edit one past audit row and show the chain catches it.

Usage:  python scripts/tamper_demo.py          # tamper (changes the latest application number)
        python scripts/tamper_demo.py --undo   # restore the original row
"""
import json
import sys
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "data" / "audit-chain.jsonl"
BAK = LOG.with_suffix(".pre-tamper")

if "--undo" in sys.argv:
    if BAK.exists():
        LOG.write_text(BAK.read_text(encoding="utf-8"), encoding="utf-8")
        BAK.unlink()
        print("restored original audit log")
    sys.exit(0)

lines = LOG.read_text(encoding="utf-8").splitlines()
BAK.write_text("\n".join(lines) + "\n", encoding="utf-8")
for i in range(len(lines) - 1, -1, -1):
    row = json.loads(lines[i])
    if row["event"] in ("application_submitted", "consent_given", "form_filled"):
        before = json.dumps(row["detail"], ensure_ascii=False)
        if "application_no" in row["detail"]:
            row["detail"]["application_no"] = "SSP-IC-000000-99999"
        else:
            row["detail"]["method"] = "typed-by-someone-else"
        lines[i] = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        print(f"tampered row #{row['seq']} ({row['event']})\n  before: {before}\n  after:  {json.dumps(row['detail'], ensure_ascii=False)}")
        break
LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("now press 'Verify chain' in the app")
