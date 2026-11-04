"""Write a synthetic, password-protected statement for the e2e tests and print its facts as JSON.

    uv run --project ../backend python make_fixture.py <out.pdf> <password> <seed>

The PDF is generated from fake data (generic_table layout) and should live in a temporary
directory. Never commit it.
"""

import json
import sys
from pathlib import Path

from finboard.parsers.builtin.generic_table.fixtures import GenericTableFixtures


def main() -> None:
    out, password, seed = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    data, statement = GenericTableFixtures().build(seed, 14, encrypted_with=password)
    out.write_bytes(data)
    print(
        json.dumps(
            {
                "rows": len(statement.transactions),
                "account_hint": statement.account_hint,
                "first_description": statement.transactions[0].description,
            }
        )
    )


if __name__ == "__main__":
    main()
