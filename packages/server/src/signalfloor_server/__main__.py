import sys

from signalfloor_server.cli import main

# Guarded, because the server's worker processes import this module again when they start. An
# unguarded call here started a second server in every one of them, which then failed to bind.
if __name__ == "__main__":
    sys.exit(main())
