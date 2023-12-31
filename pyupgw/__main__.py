"""Entry point to the command-line interface"""


def main():
    """Run ``pyupgw`` as script"""

    try:
        from .cli import cli  # pylint: disable=import-outside-toplevel
    except ImportError:
        print("Unable to load CLI. Perhaps missing [cli] extras?")
    else:
        cli()  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
