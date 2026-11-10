"""Merge only discovery additions onto the latest repository data."""
import json
import subprocess
import sys
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}


def base(path):
    result = subprocess.run(["git", "show", "HEAD:" + path], capture_output=True, text=True)
    return json.loads(result.stdout) if result.returncode == 0 else {}


def delta(previous, updated):
    known = {row["ma"] for row in previous.get("goi", [])}
    return {"goi": [row for row in updated.get("goi", []) if row["ma"] not in known],
            "phat_hien_moi": updated.get("phat_hien_moi")}


def merge(current, additions, blocked):
    known = {row["ma"] for row in current.get("goi", [])}
    added = 0
    for row in additions.get("goi", []):
        if row["ma"] in known:
            continue
        row = dict(row, hang_hoa=[h for h in row.get("hang_hoa", []) if h.get("nhom") not in blocked])
        if not row["hang_hoa"]:
            continue
        current.setdefault("goi", []).append(row)
        known.add(row["ma"])
        added += 1
    if added:
        current["goi"].sort(key=lambda row: row.get("han", ""))
        current["phat_hien_moi"] = additions["phat_hien_moi"]
    return current


if __name__ == "__main__":
    command, filename = sys.argv[1:]
    output = "data/goi_thau.json"
    state = "data/goi_thau_discovery.json"
    if command == "prepare":
        changes = delta(base(output), read(output))
        old_state = base(state)
        changes["state"] = {key: value for key, value in read(state).items() if old_state.get(key) != value}
        Path(filename).write_text(json.dumps(changes, ensure_ascii=False), encoding="utf-8")
    elif command == "merge":
        import goi_thau as g
        changes = read(filename)
        current = merge(read(output), changes, getattr(g, "BO_NHOM_BG", set()))
        Path(output).write_text(json.dumps(current, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        current_state = read(state)
        current_state.update(changes["state"])
        Path(state).write_text(json.dumps(current_state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        raise ValueError("Expected prepare or merge")
