"""
Writes to $GITHUB_OUTPUT so the workflow YAML can read a script's result
(used by the downstream alert job's JOB1_*/JOB2_* blocks). Falls back to
just printing when GITHUB_OUTPUT isn't set (e.g. running locally/manually
outside Actions), so scripts remain runnable standalone.
"""
import os


def set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    print(f"[output] {key}={value}")
