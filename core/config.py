import copy
import json
from pathlib import Path
from typing import Any, Dict


class DidierConfig:
    def __init__(self, data: Dict[str, Any], source_path: Path) -> None:
        self._data = copy.deepcopy(data)
        self._source_path = source_path

    @property
    def source_path(self) -> Path:
        return self._source_path

    def get(self, dotted_path: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in dotted_path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def require(self, dotted_path: str) -> Any:
        value = self.get(dotted_path, default=None)
        if value is None:
            raise KeyError(f"Missing required config key: {dotted_path}")
        return value

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    @classmethod
    def from_mapping(
        cls,
        data: Dict[str, Any],
        source_path: str | Path = "<memory>",
    ) -> "DidierConfig":
        return cls(data=copy.deepcopy(data), source_path=Path(source_path))

    @classmethod
    def load(cls, path: str | Path) -> "DidierConfig":
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Config not found: {resolved}")
        data = json.loads(resolved.read_text(encoding="utf-8"))
        return cls(data=data, source_path=resolved)
