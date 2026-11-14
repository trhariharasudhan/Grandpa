"""Allow ``python -m grandpa`` to run the Grandpa CLI.

Same entry point as the ``grandpa`` console script and ``python -m grandpa.cli``.
"""

from grandpa.cli import main

if __name__ == "__main__":
    main()
