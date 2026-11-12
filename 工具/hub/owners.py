from .errors import FormatError
from .skeleton import Node, node_paths, short_name

FREE_OWNERS = {"学习方法", "个人探索"}


def valid_owners(projects: dict[str, list[Node]], concepts) -> set[str]:
    """Every value 「所属」 may take: project paths, concept cards and the two free labels."""
    owners = set(FREE_OWNERS)
    for name, roots in projects.items():
        owners.add(name)
        owners.update(f"{name}/{path}" for path in node_paths(roots))
    owners.update(f"概念/{concept.name}" for concept in concepts)
    return owners


def check_owner(value: str, valid: set[str], source: str, line: int) -> FormatError | None:
    normalized = "/".join(short_name(part) for part in value.strip().split("/"))
    if normalized in valid:
        return None
    return FormatError(source, line, f"所属不存在：{value.strip()}")
