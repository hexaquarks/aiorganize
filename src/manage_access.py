"""Revoke an installation using the app owner's AWS credentials."""

import argparse
from uuid import UUID

from .access import from_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installation", type=UUID, help="Installation UUID from its saved grouping records")
    args = parser.parse_args()

    access = from_environment()
    access.table.put_item(Item={"id": f"revoked:{args.installation}"})
    print(f"Revoked installation {args.installation}.")


if __name__ == "__main__":
    main()
