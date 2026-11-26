"""Configure a webhook for the existing Evolution API instance.

Run explicitly with --apply; the implementation is importable and tested in
sentinela.infrastructure.webhook_setup.
"""
from sentinela.infrastructure.webhook_setup import main


if __name__ == "__main__":
    main()
