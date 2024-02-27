"""Entry point to the command-line interface"""


def main():
    """Run ``pyupgw`` as script"""

    try:
        from .cli import cli
    except ImportError:
        print("Unable to load CLI. Perhaps missing [cli] extras?")
    else:
        cli()


if __name__ == "__main__":
    main()
