from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", type=Path)
    parser.add_argument("object_info", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    workflow = json.loads(args.workflow.read_text())
    object_info = json.loads(args.object_info.read_text())
    links = {
        int(link[0]): [str(link[1]), int(link[2])]
        for link in workflow.get("links", [])
    }
    prompt: dict[str, dict] = {}
    for node in workflow.get("nodes", []):
        node_type = str(node.get("type") or "")
        if int(node.get("mode", 0)) != 0 or node_type not in object_info:
            continue
        class_info = object_info[node_type]
        input_schema = class_info.get("input", {})
        allowed = {
            name
            for section in ("required", "optional")
            for name in input_schema.get(section, {})
        }
        inputs = {
            name: value
            for name, value in (node.get("widgets_values_named") or {}).items()
            if name in allowed
        }
        for socket in node.get("inputs", []):
            link_id = socket.get("link")
            if link_id is not None and int(link_id) in links:
                inputs[str(socket["name"])] = links[int(link_id)]
        prompt[str(node["id"])] = {
            "class_type": node_type,
            "inputs": inputs,
            "_meta": {"title": str(node.get("title") or node_type)},
        }

    args.output.write_text(json.dumps(prompt, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
