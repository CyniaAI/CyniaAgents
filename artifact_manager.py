import os
import json
import shutil
import time

ARTIFACTS_DIR = "artifacts"
ARTIFACTS_FILE = os.path.join(ARTIFACTS_DIR, "artifacts.json")
ARTIFACT_TYPES: set[str] = set()


def _load_metadata() -> list[dict]:
    if os.path.exists(ARTIFACTS_FILE):
        with open(ARTIFACTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_metadata(data: list[dict]) -> None:
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(ARTIFACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def register_artifact_type(name: str) -> None:
    """Register a new artifact type that components may produce."""
    ARTIFACT_TYPES.add(name)


def write_artifact(component: str, src_path: str, remark: str, artifact_type: str) -> str:
    """Store a file as an artifact and record its metadata."""
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(f"Unregistered artifact type: {artifact_type}")
    if not os.path.isfile(src_path):
        raise FileNotFoundError(src_path)
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    base = os.path.basename(src_path)
    unique = f"{uuid.uuid4()}_{base}"
    dst_path = os.path.join(ARTIFACTS_DIR, unique)
    shutil.copy2(src_path, dst_path)
    size = os.path.getsize(dst_path)
    data = _load_metadata()
    data.append({
        "file": unique,
        "component": component,
        "size": size,
        "remark": remark,
        "type": artifact_type,
    })
    _save_metadata(data)
    return dst_path


def list_artifacts() -> list[dict]:
    """Return metadata for all stored artifacts."""
    data = _load_metadata()
    valid = []
    for art in data:
        path = os.path.join(ARTIFACTS_DIR, art.get("file", ""))
        if os.path.isfile(path):
            valid.append(art)
    return valid
