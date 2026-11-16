import argparse
import json
from pathlib import Path
from typing import Any, Union

import msgspec

from mapi.models.response import ResponseMetadata


def format_type(type_hint: Any) -> str:
    """Formats a type hint into a readable string."""
    if hasattr(type_hint, "__origin__") and type_hint.__origin__ is Union:
        args = getattr(type_hint, "__args__", ())
        if len(args) == 2 and args[1] is type(None):
            return f"Optional[{format_type(args[0])}]"
    if hasattr(type_hint, "__name__"):
        return type_hint.__name__
    return str(type_hint).replace("typing.", "")


def show_schema():
    """Prints the standard response format of the mapi SDK."""
    print("#-- mapi SDK Standard Response Format --#\n")
    metadata_fields = {
        f.name: format_type(f.type) for f in msgspec.structs.fields(ResponseMetadata)
    }
    response_structure = {
        "data": "# The JSON payload from the API service (or null on error).",
        "metadata": metadata_fields,
    }
    print(msgspec.yaml.encode(response_structure).decode("utf-8"))


def show_data(file_path: Path):
    """Loads a JSON file and pretty-prints it."""
    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        return

    print(f"#-- Displaying contents of: {file_path.name} --#\n")
    with open(file_path) as f:
        data = json.load(f)
        print(json.dumps(data, indent=2))


def main():
    """Main function for the utility."""
    parser = argparse.ArgumentParser(
        description="Show the mapi SDK response format or pretty-print a response file."
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="(Optional) Path to a JSON response file to display.",
    )
    args = parser.parse_args()

    if args.file:
        show_data(args.file)
    else:
        show_schema()


if __name__ == "__main__":
    main()
